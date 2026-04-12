#!/usr/bin/env python3
"""
K1086: A4f on TLT with MOVE — Testing Asset-Matched Regressor Theory on Bonds
=============================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation (follows K1085 Gold discovery):
  K1085 found on GLD:
    - A4f-VIX DM t=+1.83 FAIL
    - A4f-GVZ (gold IV) DM t=+4.46 PASS
  Theory: A4f structure is general, but tau regressor must match the asset's own IV.

  BOND TEST:
  - TLT (20+yr Treasury ETF) with MOVE (Treasury option IV, the "VIX of bonds").
  - Prediction: A4f-MOVE on TLT >> A4f-VIX on TLT.
  - If PASS: K1085 + K1086 validate asset-matched theory across equity/gold/bonds.
  - If FAIL: K1085 gold finding is special, not a general principle.

Hypotheses:
  H1: TLT A4f-VIX DM t < 3 (FAIL, analogous to GLD-VIX)
  H2: TLT A4f-MOVE DM t > 3 (PASS, analogous to GLD-GVZ)
  H3: A4f-MOVE vs A4f-VIX on TLT: MOVE Harvey-significantly beats VIX
  H4: MOVE stability across rising-rate regime (2022 TLT -32%) vs easing regime

Models:
  - GJR-GARCH(1,1) baseline
  - A4f-VIX: tau = theta0 + theta1 * VIX_{t-1}^2, g = GJR, Engle 2013 denom=tau
  - A4f-MOVE: tau = theta0 + theta1 * MOVE_{t-1}^2
  - A4f-COMBO: tau = theta0 + theta1 * VIX_{t-1}^2 + theta2 * MOVE_{t-1}^2

Design:
  - OOS window: 2007-01-02 ~ 2026-04-10 (aligned with Paper 9 horizon)
  - Rolling window = 2000 days, refit every 63 days (quarterly)
  - Training window before 2007 OOS start uses pre-2007 data (TLT IPO 2002-07-30,
    MOVE from 2003-01-02). Thus earliest train start ~ 2003-01; we push OOS
    start to 2011-01-02 to ensure full 2000-day window entirely from MOVE-
    available period.
  - Crisis sub-periods: 2008 GFC (TLT rally), 2013 Taper Tantrum,
    2020 COVID, 2022 Rising-Rate (TLT worst drawdown)
  - Regime buckets: VIX-bucket and MOVE-bucket analyses

Data:
  - TLT: yfinance Adj Close 2003-01-02 ~ 2026-04-10
  - MOVE: yfinance ^MOVE Close
  - VIX: yfinance ^VIX Close

Evaluation:
  - QLIKE on r^2 (Patton 2011, proxy-robust)
  - DM test with Newey-West HAC (Harvey 2016: |t| > 3.0)
  - Spearman rank correlation
  - Bootstrap 95% CI (moving block)

References:
  - Engle, Ghysels & Sohn (2013). RES 95(3):776-797. GARCH-MIDAS.
  - Patton (2011). J Econometrics 160:246-256. Volatility forecast comparison.
  - Harvey, Leybourne & Newbold (2016). t>3.0 threshold.
  - K1075 (A4f extended history SPY), K1085 (A4f-GVZ on GLD).

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1086
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
EXPERIMENT_ID = "K1086"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1086_results.json')

# ========================================================================
# CONFIGURATION
# ========================================================================
DATA_START = '2003-01-02'  # MOVE & TLT both available
DATA_END = '2026-04-11'
WINDOW = 2000
REFIT_EVERY = 63

# OOS starts when we have 2000 days of MOVE-era training data.
# 2003-01-02 + 2000 trading days ~= 2010-12 => OOS start 2011-01-01
OOS_WINDOWS = [
    ('Full_OOS', '2011-01-01', '2026-04-11'),
]

# Crisis sub-periods (all within OOS)
CRISIS_PERIODS = [
    ('Euro_Debt', '2011-06-01', '2012-06-30'),
    ('Taper_Tantrum', '2013-05-01', '2013-12-31'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Rising_Rates_2022', '2022-01-01', '2022-12-31'),
]

# VIX and MOVE buckets (both in raw index units)
VIX_BUCKETS = [
    ('VIX_Low', 0, 15),
    ('VIX_Normal', 15, 25),
    ('VIX_High', 25, 40),
    ('VIX_Extreme', 40, 200),
]
MOVE_BUCKETS = [
    ('MOVE_Low', 0, 70),
    ('MOVE_Normal', 70, 100),
    ('MOVE_High', 100, 140),
    ('MOVE_Extreme', 140, 400),
]

MODEL_KEYS = ['GJR', 'A4f_VIX', 'A4f_MOVE', 'A4f_COMBO']

print("=" * 74)
print(f"{EXPERIMENT_ID}: A4f on TLT with MOVE — Asset-matched regressor theory (bonds)")
print(f"  OOS: {OOS_WINDOWS[0][1]} ~ {OOS_WINDOWS[0][2]}, W={WINDOW}, refit={REFIT_EVERY}")
print(f"  Models: {', '.join(MODEL_KEYS)}")
print("=" * 74)

# ========================================================================
# SECTION 1: DATA LOADING
# ========================================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf


def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


tlt_raw = _flatten(yf.download('TLT', start=DATA_START, end=DATA_END,
                               progress=False, auto_adjust=False))
tlt_px = tlt_raw['Adj Close'] if 'Adj Close' in tlt_raw.columns else tlt_raw['Close']
tlt_ret = np.log(tlt_px / tlt_px.shift(1))

vix_raw = _flatten(yf.download('^VIX', start=DATA_START, end=DATA_END,
                               progress=False, auto_adjust=False))
vix_close = vix_raw['Close']

move_raw = _flatten(yf.download('^MOVE', start=DATA_START, end=DATA_END,
                                progress=False, auto_adjust=False))
move_close = move_raw['Close']

df = pd.DataFrame({
    'price': tlt_px,
    'log_ret': tlt_ret,
    'VIX': vix_close,
    'MOVE': move_close,
}).dropna()

n_total = len(df)
print(f"  Aligned data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
move = df['MOVE'].values
r2 = ret ** 2
dates = df.index


# ========================================================================
# SECTION 2: DIAGNOSTICS
# ========================================================================
print("\n[2] Diagnostics (TLT)...")
print(f"  Full sample:")
print(f"    TLT return mean (ann): {np.mean(ret)*252:.4f}")
print(f"    TLT return std (ann):  {np.std(ret)*np.sqrt(252):.4f}")
print(f"    TLT skew:              {stats.skew(ret):.3f}")
print(f"    TLT kurtosis:          {stats.kurtosis(ret):.3f}")
print(f"    VIX mean / max:        {np.mean(vix):.2f} / {np.max(vix):.2f}")
print(f"    MOVE mean / max:       {np.mean(move):.2f} / {np.max(move):.2f}")
print(f"    Corr(VIX, MOVE):       {np.corrcoef(vix, move)[0, 1]:.3f}")

# TLT peak-to-trough drawdown 2022
tlt_cum = np.exp(np.cumsum(np.nan_to_num(ret)))
peak = np.maximum.accumulate(tlt_cum)
dd = tlt_cum / peak - 1
print(f"    Max drawdown (full):   {np.min(dd):.3f} on {dates[np.argmin(dd)].date()}")

for name, start, end in OOS_WINDOWS:
    mask = (dates >= start) & (dates <= end)
    n_w = mask.sum()
    vix_w = vix[mask]
    move_w = move[mask]
    ret_w = ret[mask]
    print(f"  {name} ({start} to {end}): n={n_w}")
    print(f"    VIX max={np.max(vix_w):.1f}, MOVE max={np.max(move_w):.1f}, "
          f"ret std={np.std(ret_w)*np.sqrt(252):.3f}")


# ========================================================================
# SECTION 3: MODELS
# ========================================================================
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
    bounds = [(1e-10, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
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


def _make_a4f_loglik(returns, regressor_arrays):
    """
    Factory for A4f negative log-likelihood given list of regressor arrays (pre-lagged and squared).
    Params: [theta0, theta_i..., omega_g, alpha, gamma, beta]
    """
    n = len(returns)
    K = len(regressor_arrays)
    regs = np.stack(regressor_arrays, axis=1)  # n x K

    def neg_loglik(params):
        theta0 = params[0]
        thetas = np.array(params[1:1+K])
        omega_g = params[1+K]
        alpha = params[2+K]
        gamma_p = params[3+K]
        beta = params[4+K]

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if np.any(thetas < 0):
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        tau_raw = theta0 + regs @ thetas
        tau = np.maximum(tau_raw, 1e-16)

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
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    return neg_loglik


def fit_a4f(returns, regressor_raw_list):
    """
    regressor_raw_list: list of arrays (len n) with raw values; we internally lag and square.
    Returns params = [theta0, *thetas, omega_g, alpha, gamma, beta], converged.
    """
    n = len(returns)
    K = len(regressor_raw_list)
    regs_lagged_sq = []
    for raw in regressor_raw_list:
        lagged = np.empty(n)
        lagged[0] = raw[0]
        lagged[1:] = raw[:-1]
        regs_lagged_sq.append(lagged ** 2)

    neg_loglik = _make_a4f_loglik(returns, regs_lagged_sq)

    var0 = np.var(returns)
    # Means of lagged-squared regressors
    means = [np.mean(x) + 1e-10 for x in regs_lagged_sq]

    # Multiple starting points
    starts = []
    for scale in [1.0, 0.5, 1.5]:
        theta0 = var0 * 0.05 * scale
        thetas_init = [var0 / (K * m) * scale for m in means]
        starts.append([theta0] + thetas_init + [0.05, 0.05, 0.05, 0.90])

    # Bounds
    bounds = [(-1e-2, 1e-2)]  # theta0
    for _ in range(K):
        bounds.append((0.0, 1e-2))  # theta_i positive
    bounds.extend([
        (1e-6, 1.0),    # omega_g
        (1e-4, 0.3),    # alpha
        (1e-4, 0.3),    # gamma
        (0.5, 0.999),   # beta
    ])

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


def a4f_forecast_1step(params, K, reg_lag_vals, r_prev, g_prev):
    """
    reg_lag_vals: list of length K, each is value at t-1 (raw, not squared).
    Returns sigma2_t and updated g_new (for recursion).
    """
    theta0 = params[0]
    thetas = np.array(params[1:1+K])
    omega_g = params[1+K]
    alpha = params[2+K]
    gamma_p = params[3+K]
    beta = params[4+K]

    reg_sq = np.array([v**2 for v in reg_lag_vals])
    tau_t = max(theta0 + float(np.dot(thetas, reg_sq)), 1e-16)

    u_prev = r_prev / np.sqrt(tau_t)
    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
    g_new = omega_g + alpha * u_prev**2 + asym + beta * g_prev
    g_new = max(g_new, 1e-10)
    return tau_t * g_new, g_new, tau_t


def init_a4f_state(params, K, train_ret, train_regressors):
    """Initialize g recursion through training data. Return final g and last tau."""
    theta0 = params[0]
    thetas = np.array(params[1:1+K])
    omega_g = params[1+K]
    alpha = params[2+K]
    gamma_p = params[3+K]
    beta = params[4+K]

    n = len(train_ret)
    # Build lagged regressors
    regs_lag_sq = []
    for raw in train_regressors:
        lagged = np.empty(n)
        lagged[0] = raw[0]
        lagged[1:] = raw[:-1]
        regs_lag_sq.append(lagged ** 2)

    tau = np.maximum(theta0 + np.sum(np.stack(regs_lag_sq, axis=1) * thetas, axis=1), 1e-16)
    persist = alpha + gamma_p / 2.0 + beta
    g = omega_g / (1.0 - persist)
    for i in range(1, n):
        u_prev = train_ret[i-1] / np.sqrt(tau[i])
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha * u_prev**2 + asym + beta * g
        g = max(g, 1e-10)
    return g, tau[-1]


# ========================================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ========================================================================
print("\n[4] Out-of-sample forecasting (4 models)...")

# OOS mask
oos_mask = np.zeros(n_total, dtype=bool)
window_tags = np.empty(n_total, dtype=object)
for name, start, end in OOS_WINDOWS:
    m = (dates >= start) & (dates <= end)
    oos_mask |= m
    for idx in np.where(m)[0]:
        window_tags[idx] = name

oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  Total OOS obs: {n_oos}")

for name, start, end in OOS_WINDOWS:
    start_idx = np.where(dates >= start)[0][0]
    print(f"    {name}: start_idx={start_idx}, window={WINDOW}, "
          f"sufficient={'YES' if start_idx >= WINDOW else 'NO'}")

# Forecast storage
forecasts = {k: np.full(n_oos, np.nan) for k in MODEL_KEYS}

refit_log = []
refit_count = 0

# States
gjr_params = None
gjr_h = None

a4f_vix_params = None
a4f_vix_g = None
a4f_move_params = None
a4f_move_g = None
a4f_combo_params = None
a4f_combo_g = None

prev_window = None

for t_idx, abs_idx in enumerate(oos_indices):
    current_window = window_tags[abs_idx]

    # Refit trigger
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
        train_move = move[train_start:abs_idx]

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
        a4f_v_p, a4f_v_conv = fit_a4f(train_ret, [train_vix])
        if a4f_v_p is not None:
            a4f_vix_params = a4f_v_p
            a4f_vix_g, _ = init_a4f_state(a4f_v_p, 1, train_ret, [train_vix])
        else:
            a4f_v_conv = False

        # A4f-MOVE
        a4f_m_p, a4f_m_conv = fit_a4f(train_ret, [train_move])
        if a4f_m_p is not None:
            a4f_move_params = a4f_m_p
            a4f_move_g, _ = init_a4f_state(a4f_m_p, 1, train_ret, [train_move])
        else:
            a4f_m_conv = False

        # A4f-COMBO
        a4f_c_p, a4f_c_conv = fit_a4f(train_ret, [train_vix, train_move])
        if a4f_c_p is not None:
            a4f_combo_params = a4f_c_p
            a4f_combo_g, _ = init_a4f_state(a4f_c_p, 2, train_ret, [train_vix, train_move])
        else:
            a4f_c_conv = False

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            'gjr_conv': bool(gjr_conv),
            'a4f_vix_conv': bool(a4f_v_conv),
            'a4f_move_conv': bool(a4f_m_conv),
            'a4f_combo_conv': bool(a4f_c_conv),
            'a4f_vix_theta1': float(a4f_vix_params[1]) if a4f_vix_params is not None else None,
            'a4f_move_theta1': float(a4f_move_params[1]) if a4f_move_params is not None else None,
            'a4f_combo_theta_vix': float(a4f_combo_params[1]) if a4f_combo_params is not None else None,
            'a4f_combo_theta_move': float(a4f_combo_params[2]) if a4f_combo_params is not None else None,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # === Produce forecasts for day abs_idx ===
    r_prev = ret[abs_idx - 1]
    vix_lag = vix[abs_idx - 1]
    move_lag = move[abs_idx - 1]

    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        forecasts['GJR'][t_idx] = h_new
        gjr_h = h_new

    if a4f_vix_params is not None:
        s2, g_new, _ = a4f_forecast_1step(a4f_vix_params, 1, [vix_lag], r_prev, a4f_vix_g)
        forecasts['A4f_VIX'][t_idx] = s2
        a4f_vix_g = g_new

    if a4f_move_params is not None:
        s2, g_new, _ = a4f_forecast_1step(a4f_move_params, 1, [move_lag], r_prev, a4f_move_g)
        forecasts['A4f_MOVE'][t_idx] = s2
        a4f_move_g = g_new

    if a4f_combo_params is not None:
        s2, g_new, _ = a4f_forecast_1step(a4f_combo_params, 2, [vix_lag, move_lag],
                                          r_prev, a4f_combo_g)
        forecasts['A4f_COMBO'][t_idx] = s2
        a4f_combo_g = g_new

    prev_window = current_window

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")


# ========================================================================
# SECTION 5: EVALUATION
# ========================================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_indices]
oos_dates = dates[oos_indices]
oos_vix = vix[oos_indices]
oos_move = move[oos_indices]
oos_vix_lag = np.empty(n_oos)
oos_move_lag = np.empty(n_oos)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]
    oos_move_lag[i] = move[idx - 1] if idx > 0 else move[0]


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


# Global valid mask: all models have valid forecast
valid_all = np.ones(n_oos, dtype=bool)
for k in MODEL_KEYS:
    valid_all &= (~np.isnan(forecasts[k]) & (forecasts[k] > 0))
n_valid = valid_all.sum()
print(f"  Valid joint observations (all 4 models): {n_valid}/{n_oos}")


def model_stats(fc_arr, r2_arr):
    ql = qlike_loss(fc_arr, r2_arr)
    rho, _ = stats.spearmanr(fc_arr, r2_arr)
    return float(np.mean(ql)), float(rho)


def dm_vs_gjr(model_key, mask):
    fc_g = forecasts['GJR'][mask]
    fc_m = forecasts[model_key][mask]
    r2_v = oos_r2[mask]
    ql_g_arr = qlike_loss(fc_g, r2_v)
    ql_m_arr = qlike_loss(fc_m, r2_v)
    d = ql_g_arr - ql_m_arr  # positive => model better than GJR
    t, p, T = hac_dm_test(d)
    ci = bootstrap_ci_mean_diff(d)
    return t, p, T, ci


def dm_pair(a_key, b_key, mask):
    """DM test: A vs B. Positive => A better."""
    fc_a = forecasts[a_key][mask]
    fc_b = forecasts[b_key][mask]
    r2_v = oos_r2[mask]
    ql_a = qlike_loss(fc_a, r2_v)
    ql_b = qlike_loss(fc_b, r2_v)
    d = ql_b - ql_a  # positive => A better than B
    t, p, T = hac_dm_test(d)
    return t, p, T


results = {
    'metadata': {},
    'full_oos': {},
    'per_window': {},
    'crisis_subperiods': {},
    'vix_buckets': {},
    'move_buckets': {},
    'pairwise_dm': {},
    'refit_log': refit_log,
}

# --- Full OOS ---
if n_valid > 0:
    print(f"\n  FULL OOS (n={n_valid}):")
    print(f"  {'Model':<12} {'QLIKE':>10} {'Spearman':>10} {'DM vs GJR':>10} {'Harvey':>8}")
    full = {}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][valid_all], oos_r2[valid_all])
        if k == 'GJR':
            dm_t, dm_p, T, ci = None, None, n_valid, [None, None]
        else:
            dm_t, dm_p, T, ci = dm_vs_gjr(k, valid_all)
        harvey = (dm_t is not None and np.isfinite(dm_t) and abs(dm_t) > 3.0 and dm_t > 0)
        full[k] = {
            'n': int(n_valid), 'qlike': ql, 'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
            'dm_p_vs_gjr': float(dm_p) if dm_p is not None and np.isfinite(dm_p) else None,
            'harvey_pass_vs_gjr': bool(harvey),
            'bootstrap_ci_95': [ci[0] if ci[0] is not None else None,
                                ci[1] if ci[1] is not None else None],
        }
        dm_display = f"{dm_t:+.3f}" if dm_t is not None and np.isfinite(dm_t) else "--"
        print(f"  {k:<12} {ql:>10.6f} {rho:>10.3f} {dm_display:>10} "
              f"{'PASS' if harvey else 'FAIL':>8}")
    results['full_oos'] = full

# --- Per-window ---
for name, start, end in OOS_WINDOWS:
    mask = (oos_dates >= start) & (oos_dates <= end) & valid_all
    n_w = mask.sum()
    if n_w < 30:
        continue
    res_w = {'n': int(n_w), 'start': start, 'end': end}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask], oos_r2[mask])
        if k == 'GJR':
            dm_t, dm_p = None, None
        else:
            dm_t, dm_p, _, _ = dm_vs_gjr(k, mask)
        harvey = (dm_t is not None and np.isfinite(dm_t) and abs(dm_t) > 3.0 and dm_t > 0)
        res_w[k] = {
            'qlike': ql, 'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
            'dm_p_vs_gjr': float(dm_p) if dm_p is not None and np.isfinite(dm_p) else None,
            'harvey_pass_vs_gjr': bool(harvey),
        }
    results['per_window'][name] = res_w

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods:")
header = f"  {'Crisis':<20} {'n':>6} {'GJR_QL':>9} {'VIX_QL':>9} {'MOVE_QL':>9} {'COMBO_QL':>9}  {'MOVE_DM':>8} {'VIX_DM':>8}"
print(header)
for cname, cstart, cend in CRISIS_PERIODS:
    mask_c = (oos_dates >= cstart) & (oos_dates <= cend) & valid_all
    n_c = mask_c.sum()
    if n_c < 30:
        print(f"  {cname:<20} insufficient (n={n_c})")
        continue
    res_c = {'n': int(n_c), 'start': cstart, 'end': cend}
    qls = {}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_c], oos_r2[mask_c])
        qls[k] = ql
        if k == 'GJR':
            dm_t, dm_p = None, None
        else:
            dm_t, dm_p, _, _ = dm_vs_gjr(k, mask_c)
        harvey = (dm_t is not None and np.isfinite(dm_t) and abs(dm_t) > 3.0 and dm_t > 0)
        res_c[k] = {
            'qlike': ql, 'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
            'dm_p_vs_gjr': float(dm_p) if dm_p is not None and np.isfinite(dm_p) else None,
            'harvey_pass_vs_gjr': bool(harvey),
        }
    res_c['vix_mean'] = float(np.mean(oos_vix[mask_c]))
    res_c['move_mean'] = float(np.mean(oos_move[mask_c]))
    res_c['vix_max'] = float(np.max(oos_vix[mask_c]))
    res_c['move_max'] = float(np.max(oos_move[mask_c]))
    move_dm = res_c['A4f_MOVE']['dm_t_vs_gjr']
    vix_dm = res_c['A4f_VIX']['dm_t_vs_gjr']
    print(f"  {cname:<20} {n_c:>6} {qls['GJR']:>9.5f} {qls['A4f_VIX']:>9.5f} "
          f"{qls['A4f_MOVE']:>9.5f} {qls['A4f_COMBO']:>9.5f}  "
          f"{move_dm:>+8.3f} {vix_dm:>+8.3f}")
    results['crisis_subperiods'][cname] = res_c

# --- VIX buckets ---
print("\n  VIX bucket analysis (A4f_MOVE vs GJR):")
print(f"  {'Bucket':<14} {'Range':<12} {'n':>6} {'GJR_QL':>9} {'MOVE_QL':>9} {'Diff%':>8} {'DM':>8}")
for bname, bmin, bmax in VIX_BUCKETS:
    mask_b = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & valid_all
    n_b = mask_b.sum()
    if n_b < 20:
        print(f"  {bname:<14} [{bmin},{bmax}) insufficient (n={n_b})")
        results['vix_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    res_b = {'n': int(n_b), 'range': [bmin, bmax]}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_b], oos_r2[mask_b])
        if k == 'GJR':
            dm_t = None
        else:
            dm_t, _, _, _ = dm_vs_gjr(k, mask_b)
        res_b[k] = {
            'qlike': ql, 'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
        }
    diff_pct = (res_b['A4f_MOVE']['qlike'] - res_b['GJR']['qlike']) / abs(res_b['GJR']['qlike']) * 100
    dm_t_m = res_b['A4f_MOVE']['dm_t_vs_gjr']
    print(f"  {bname:<14} [{bmin},{bmax})   {n_b:>6} {res_b['GJR']['qlike']:>9.5f} "
          f"{res_b['A4f_MOVE']['qlike']:>9.5f} {diff_pct:>+7.2f}% {dm_t_m:>+8.3f}")
    results['vix_buckets'][bname] = res_b

# --- MOVE buckets ---
print("\n  MOVE bucket analysis (A4f_MOVE vs GJR):")
print(f"  {'Bucket':<14} {'Range':<12} {'n':>6} {'GJR_QL':>9} {'MOVE_QL':>9} {'Diff%':>8} {'DM':>8}")
for bname, bmin, bmax in MOVE_BUCKETS:
    mask_b = (oos_move_lag >= bmin) & (oos_move_lag < bmax) & valid_all
    n_b = mask_b.sum()
    if n_b < 20:
        print(f"  {bname:<14} [{bmin},{bmax}) insufficient (n={n_b})")
        results['move_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    res_b = {'n': int(n_b), 'range': [bmin, bmax]}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_b], oos_r2[mask_b])
        if k == 'GJR':
            dm_t = None
        else:
            dm_t, _, _, _ = dm_vs_gjr(k, mask_b)
        res_b[k] = {
            'qlike': ql, 'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
        }
    diff_pct = (res_b['A4f_MOVE']['qlike'] - res_b['GJR']['qlike']) / abs(res_b['GJR']['qlike']) * 100
    dm_t_m = res_b['A4f_MOVE']['dm_t_vs_gjr']
    print(f"  {bname:<14} [{bmin},{bmax})   {n_b:>6} {res_b['GJR']['qlike']:>9.5f} "
          f"{res_b['A4f_MOVE']['qlike']:>9.5f} {diff_pct:>+7.2f}% {dm_t_m:>+8.3f}")
    results['move_buckets'][bname] = res_b

# --- Pairwise DM (MOVE vs VIX, COMBO vs MOVE) ---
print("\n  Pairwise DM tests (positive t => first model better):")
pairs = [
    ('A4f_MOVE', 'A4f_VIX'),
    ('A4f_COMBO', 'A4f_MOVE'),
    ('A4f_COMBO', 'A4f_VIX'),
]
for a, b in pairs:
    t, p, T = dm_pair(a, b, valid_all)
    harvey = np.isfinite(t) and abs(t) > 3.0 and t > 0
    key = f"{a}_vs_{b}"
    results['pairwise_dm'][key] = {
        'dm_t': float(t) if np.isfinite(t) else None,
        'dm_p': float(p) if np.isfinite(p) else None,
        'n': int(T),
        'harvey_pass': bool(harvey),
    }
    print(f"    {a} vs {b}: t={t:+.3f}, p={p:.4f}, Harvey={'PASS' if harvey else 'FAIL'}")


# ========================================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ========================================================================
print("\n" + "=" * 74)
print("HYPOTHESIS VERDICTS")
print("=" * 74)

full = results['full_oos']
vix_dm = full['A4f_VIX']['dm_t_vs_gjr'] if full else None
move_dm = full['A4f_MOVE']['dm_t_vs_gjr'] if full else None
combo_dm = full['A4f_COMBO']['dm_t_vs_gjr'] if full else None

# H1: VIX on TLT FAILS (Harvey)
h1_pass = (vix_dm is not None and abs(vix_dm) <= 3.0)
# H2: MOVE on TLT PASSES (Harvey)
h2_pass = (move_dm is not None and abs(move_dm) > 3.0 and move_dm > 0)
# H3: MOVE Harvey-sig beats VIX (pairwise)
mv_pair = results['pairwise_dm'].get('A4f_MOVE_vs_A4f_VIX', {})
h3_t = mv_pair.get('dm_t')
h3_pass = (h3_t is not None and abs(h3_t) > 3.0 and h3_t > 0)
# H4: MOVE stable across regimes (2022 sub-period Harvey >0)
rr22 = results['crisis_subperiods'].get('Rising_Rates_2022', {})
rr22_mv = (rr22.get('A4f_MOVE') or {}).get('dm_t_vs_gjr')
h4_pass = (rr22_mv is not None and rr22_mv > 0)  # beat GJR in 2022

print(f"  H1 (TLT A4f-VIX does NOT Harvey-PASS): "
      f"{'PASS' if h1_pass else 'FAIL'}  (|t|={abs(vix_dm):.3f}, need <=3)")
print(f"  H2 (TLT A4f-MOVE Harvey-PASS):          "
      f"{'PASS' if h2_pass else 'FAIL'}  (t={move_dm:+.3f}, need >3)")
print(f"  H3 (MOVE beats VIX, Harvey):            "
      f"{'PASS' if h3_pass else 'FAIL'}  (t={h3_t:+.3f}, need >3)")
print(f"  H4 (MOVE beats GJR in 2022 rate cycle): "
      f"{'PASS' if h4_pass else 'FAIL'}  "
      f"(t={rr22_mv:+.3f} in 2022)" if rr22_mv is not None else "  H4: insufficient data")

overall_verdict = ('PASS' if (h2_pass and h3_pass)
                   else ('PARTIAL' if (h2_pass or h3_pass) else 'FAIL'))
print(f"\n  OVERALL (asset-matched theory on bonds): {overall_verdict}")

results['hypothesis_verdicts'] = {
    'H1_TLT_VIX_not_harvey': 'PASS' if h1_pass else 'FAIL',
    'H2_TLT_MOVE_harvey': 'PASS' if h2_pass else 'FAIL',
    'H3_MOVE_beats_VIX': 'PASS' if h3_pass else 'FAIL',
    'H4_MOVE_in_2022': 'PASS' if h4_pass else 'FAIL',
    'overall': overall_verdict,
}


# ========================================================================
# SECTION 7: METADATA + SAVE
# ========================================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'TLT',
    'regressors_tested': ['VIX', 'MOVE', 'VIX+MOVE'],
    'data_start': DATA_START,
    'data_end': DATA_END,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_total': int(n_total),
    'n_oos': int(n_oos),
    'n_valid': int(n_valid),
    'n_refits': int(refit_count),
    'oos_windows': [(n, s, e) for n, s, e in OOS_WINDOWS],
    'crisis_periods': [(n, s, e) for n, s, e in CRISIS_PERIODS],
    'vix_buckets': [(n, lo, hi) for n, lo, hi in VIX_BUCKETS],
    'move_buckets': [(n, lo, hi) for n, lo, hi in MOVE_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1086 brief)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals. RES 95(3):776-797.',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). t>3.0 threshold.',
        'K1075 (SPY A4f-VIX extended), K1085 (GLD A4f-GVZ).',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n[7] Results saved to {RESULTS_PATH}")
print(f"    Total elapsed: {time.time() - START_TIME:.0f}s")

# ========================================================================
# SECTION 8: FIGURES
# ========================================================================
print("\n[8] Generating figures...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Figure 1: Extended DM — 4 models vs GJR
fig, ax = plt.subplots(figsize=(9, 5))
keys_ex_gjr = [k for k in MODEL_KEYS if k != 'GJR']
tvals = [results['full_oos'][k]['dm_t_vs_gjr'] for k in keys_ex_gjr]
colors = ['#d62728' if (t is not None and abs(t) > 3.0 and t > 0) else '#1f77b4'
          for t in tvals]
tvals_plot = [t if t is not None else 0 for t in tvals]
ax.bar(keys_ex_gjr, tvals_plot, color=colors, alpha=0.8, edgecolor='black')
ax.axhline(3.0, color='red', linestyle='--', label='Harvey |t|=3.0')
ax.axhline(-3.0, color='red', linestyle='--')
ax.axhline(0, color='black', linewidth=0.5)
ax.set_ylabel('DM t-statistic vs GJR (positive = model better)')
ax.set_title(f'K1086 TLT: A4f variants vs GJR, Full OOS (n={n_valid})')
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1086_extended_dm.png'), dpi=120)
plt.close()

# Figure 2: Crisis periods — A4f_MOVE vs GJR by crisis
fig, ax = plt.subplots(figsize=(10, 5))
crises = [c for c in CRISIS_PERIODS if c[0] in results['crisis_subperiods']]
cnames = [c[0] for c in crises]
move_diff = []
vix_diff = []
for cname, _, _ in crises:
    r = results['crisis_subperiods'][cname]
    move_diff.append((r['A4f_MOVE']['qlike'] - r['GJR']['qlike']) / abs(r['GJR']['qlike']) * 100)
    vix_diff.append((r['A4f_VIX']['qlike'] - r['GJR']['qlike']) / abs(r['GJR']['qlike']) * 100)
x = np.arange(len(cnames))
w = 0.35
ax.bar(x - w/2, move_diff, w, label='A4f-MOVE', color='#d62728', alpha=0.8)
ax.bar(x + w/2, vix_diff, w, label='A4f-VIX', color='#1f77b4', alpha=0.8)
ax.set_xticks(x)
ax.set_xticklabels(cnames, rotation=30, ha='right')
ax.set_ylabel('QLIKE diff vs GJR (%, negative = improvement)')
ax.set_title('K1086 TLT: A4f-MOVE vs A4f-VIX, crisis sub-periods')
ax.axhline(0, color='black', linewidth=0.5)
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1086_crisis_periods.png'), dpi=120)
plt.close()

# Figure 3: VIX vs MOVE regressor comparison
fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
models_sub = ['A4f_VIX', 'A4f_MOVE', 'A4f_COMBO']
# Left: QLIKE full OOS
qlikes = [results['full_oos'][k]['qlike'] for k in ['GJR'] + models_sub]
axes[0].bar(['GJR'] + models_sub, qlikes, color=['gray', '#1f77b4', '#d62728', '#2ca02c'],
            alpha=0.8, edgecolor='black')
axes[0].set_ylabel('QLIKE (lower = better)')
axes[0].set_title(f'Full OOS QLIKE (n={n_valid})')
axes[0].grid(alpha=0.3)
# Right: DM t-stats
dm_ts = [results['full_oos'][k]['dm_t_vs_gjr'] for k in models_sub]
dm_ts_plot = [t if t is not None else 0 for t in dm_ts]
colors2 = ['#d62728' if (t is not None and abs(t) > 3.0 and t > 0) else '#1f77b4'
           for t in dm_ts]
axes[1].bar(models_sub, dm_ts_plot, color=colors2, alpha=0.8, edgecolor='black')
axes[1].axhline(3.0, color='red', linestyle='--', label='Harvey 3.0')
axes[1].axhline(-3.0, color='red', linestyle='--')
axes[1].axhline(0, color='black', linewidth=0.5)
axes[1].set_ylabel('DM t-stat vs GJR')
axes[1].set_title('DM vs GJR (positive = better than GJR)')
axes[1].legend()
axes[1].grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1086_vix_move_compare.png'), dpi=120)
plt.close()

# Figure 4: theta1 evolution time series
fig, ax = plt.subplots(figsize=(11, 5))
rl_dates = [datetime.strptime(r['date'], '%Y-%m-%d') for r in refit_log]
vix_thetas = [r.get('a4f_vix_theta1') for r in refit_log]
move_thetas = [r.get('a4f_move_theta1') for r in refit_log]
ax.plot(rl_dates, vix_thetas, 'o-', label='A4f-VIX theta1 (VIX^2 coef)',
        color='#1f77b4', alpha=0.8, markersize=4)
ax2 = ax.twinx()
ax2.plot(rl_dates, move_thetas, 's-', label='A4f-MOVE theta1 (MOVE^2 coef)',
         color='#d62728', alpha=0.8, markersize=4)
ax.set_ylabel('theta1 (A4f-VIX)', color='#1f77b4')
ax2.set_ylabel('theta1 (A4f-MOVE)', color='#d62728')
ax.set_title('K1086 TLT: theta1 evolution over refit grid')
ax.grid(alpha=0.3)
# Combined legend
lines1, labels1 = ax.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1086_theta1_evolution.png'), dpi=120)
plt.close()

# Figure 5: Asset class × IV matrix (summary of K1075 + K1085 + K1086)
fig, ax = plt.subplots(figsize=(7.5, 4.5))
# Data: rows=(Equity SPY / Gold GLD / Bond TLT), cols=(VIX, GVZ, MOVE)
# Use K1086's own numbers; cross-K numbers as placeholder text in note
matrix_labels = ['Equity (SPY)', 'Gold (GLD)', 'Bond (TLT)']
cols = ['VIX', 'GVZ', 'MOVE']
# Hardcoded best-known indicators (from project knowledge)
# K1075 SPY A4f-VIX full t ~ 4.48; K1085 GLD A4f-VIX t=1.83, A4f-GVZ t=4.46
# K1086 TLT: read from our results
tlt_vix_t = vix_dm if vix_dm is not None else np.nan
tlt_move_t = move_dm if move_dm is not None else np.nan
matrix = np.array([
    [4.48, np.nan, np.nan],   # SPY: VIX (K1075)
    [1.83, 4.46, np.nan],     # GLD: VIX, GVZ (K1085)
    [tlt_vix_t, np.nan, tlt_move_t],   # TLT: VIX, MOVE (K1086)
])
im = ax.imshow(matrix, cmap='RdYlGn', vmin=-5, vmax=5, aspect='auto')
ax.set_xticks(np.arange(len(cols)))
ax.set_xticklabels(cols)
ax.set_yticks(np.arange(len(matrix_labels)))
ax.set_yticklabels(matrix_labels)
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if np.isnan(val):
            ax.text(j, i, 'n/a', ha='center', va='center', color='gray', fontsize=9)
        else:
            ax.text(j, i, f'{val:+.2f}', ha='center', va='center',
                    color='black', fontsize=10, fontweight='bold')
ax.set_title('Asset-matched regressor theory: A4f DM t vs GJR\n(K1075 SPY + K1085 GLD + K1086 TLT)')
plt.colorbar(im, ax=ax, label='DM t-stat')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1086_asset_class_matrix.png'), dpi=120)
plt.close()

print("  Saved: k1086_extended_dm.png, k1086_crisis_periods.png, "
      "k1086_vix_move_compare.png, k1086_theta1_evolution.png, "
      "k1086_asset_class_matrix.png")
print(f"\n{EXPERIMENT_ID} COMPLETE. Total time: {time.time() - START_TIME:.0f}s")
