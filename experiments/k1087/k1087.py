#!/usr/bin/env python3
"""
K1087: A4f on TLT with Yield-Curve Factors — Finding Bond-Matched Regressor
==========================================================================
[提出: 用戶 (Claude 執行), 執行: Claude]

Motivation (follows K1086 null result):
  K1086: TLT A4f-VIX (t=+1.43), A4f-MOVE (t=+1.36), A4f-COMBO (t=+1.44) — ALL FAIL.
  Diagnosis: TLT vol driven by yield-curve dynamics (duration risk), not option IV.

  K1087 tests YIELD-CURVE factors as alternative regressors:
  - Level (10Y yield squared)
  - Slope (|10Y - 2Y|)
  - Realized Rate Vol (|ΔY_10Y|² annualized)
  - Butterfly (|2×5Y - 2Y - 10Y|)
  - Combo (VIX + |ΔY_10Y|²)

Hypotheses:
  H1: A4f-RealRateVol DM t > 3 on TLT (realized rate vol matches duration)
  H2: A4f-Level or A4f-Slope DM t > 3 on TLT
  H3: A4f-Combo (VIX + yield) > A4f-VIX on TLT (Harvey pair test)
  H4: 2022 rate-hike regime: yield factor captures TLT drawdown better than VIX/MOVE

Models:
  - GJR-GARCH(1,1) baseline
  - A4f-VIX, A4f-MOVE (from K1086, baselines)
  - A4f-Level:  tau = theta0 + theta1 * Yield_10Y_{t-1}^2
  - A4f-Slope:  tau = theta0 + theta1 * (Yield_10Y_{t-1} - Yield_2Y_{t-1})^2
  - A4f-RealRateVol: tau = theta0 + theta1 * (ΔYield_10Y_{t-1})^2 * 252
  - A4f-Butterfly:  tau = theta0 + theta1 * (2*Y5Y_{t-1} - Y2Y_{t-1} - Y10Y_{t-1})^2
  - A4f-Combo:  tau = theta0 + theta1 * VIX_{t-1}^2 + theta2 * (ΔY_{t-1})^2 * 252

Design:
  - OOS: 2011-01-01 ~ 2026-04-10 (aligned with K1086 for direct comparability)
  - Rolling window = 2000 days, refit every 63 days (quarterly)
  - Regime buckets (VIX, MOVE, Rate-vol)
  - Crisis sub-periods: Euro_Debt, Taper_Tantrum, COVID, Rising_Rates_2022

Data:
  - TLT: yfinance Adj Close 2003-01-02 ~ 2026-04-10
  - VIX, MOVE: yfinance ^VIX, ^MOVE (K1086 baselines)
  - DGS10, DGS2, DGS5: FRED direct CSV (cached locally when available)
  - Yield units: percent (e.g., 4.5% is stored as 4.5, divided by 100 in code to decimal)

Evaluation:
  - QLIKE on r^2 (Patton 2011)
  - DM test with Newey-West HAC (Harvey 2016: |t| > 3.0)
  - Spearman rank
  - Pairwise DM (all 7 models)

References:
  - Engle, Ghysels & Sohn (2013). RES 95(3):776-797. GARCH-MIDAS.
  - Patton (2011). J Econometrics 160:246-256.
  - Harvey, Leybourne & Newbold (2016). t>3.0 threshold.
  - Litterman & Scheinkman (1991). Common factors in Treasury yields.
  - Balduzzi, Elton & Green (2001). Bond vol and yield innovations.
  - Chen, Roll & Ross (1986). Macro factors in asset pricing.
  - K1075, K1085, K1086 (prior A4f experiments).

Author: VolPred Research System
Date: 2026-04-12
Experiment ID: K1087
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
EXPERIMENT_ID = "K1087"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Locate project root (searches parents for storage/macro)
def _find_project_root(start):
    cur = start
    for _ in range(6):
        if os.path.isdir(os.path.join(cur, 'storage', 'macro')):
            return cur
        cur = os.path.dirname(cur)
    return None

PROJECT_ROOT = _find_project_root(SCRIPT_DIR) or os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1087_results.json')

# ========================================================================
# CONFIGURATION
# ========================================================================
DATA_START = '2003-01-02'
DATA_END = '2026-04-11'
WINDOW = 2000
REFIT_EVERY = 63

OOS_WINDOWS = [
    ('Full_OOS', '2011-01-01', '2026-04-11'),
]

CRISIS_PERIODS = [
    ('Euro_Debt', '2011-06-01', '2012-06-30'),
    ('Taper_Tantrum', '2013-05-01', '2013-12-31'),
    ('COVID_Crash', '2020-02-01', '2020-06-30'),
    ('Rising_Rates_2022', '2022-01-01', '2022-12-31'),
]

VIX_BUCKETS = [
    ('VIX_Low', 0, 15),
    ('VIX_Normal', 15, 25),
    ('VIX_High', 25, 40),
    ('VIX_Extreme', 40, 200),
]

# Rate-vol buckets (|dY_10Y| in bps)
RATE_VOL_BUCKETS = [
    ('RateVol_Low', 0.0, 3.0),
    ('RateVol_Normal', 3.0, 7.0),
    ('RateVol_High', 7.0, 15.0),
    ('RateVol_Extreme', 15.0, 100.0),
]

# Yield-level buckets (10Y in percent)
YIELD_BUCKETS = [
    ('Yield_Low', 0, 2.0),
    ('Yield_Mid', 2.0, 4.0),
    ('Yield_High', 4.0, 10.0),
]

MODEL_KEYS = [
    'GJR',
    'A4f_VIX',
    'A4f_MOVE',
    'A4f_Level',
    'A4f_Slope',
    'A4f_RateVol',
    'A4f_Butterfly',
    'A4f_Combo',  # VIX + RateVol
]

print("=" * 78)
print(f"{EXPERIMENT_ID}: TLT A4f with yield-curve factors")
print(f"  OOS: {OOS_WINDOWS[0][1]} ~ {OOS_WINDOWS[0][2]}, W={WINDOW}, refit={REFIT_EVERY}")
print(f"  Models: {', '.join(MODEL_KEYS)}")
print("=" * 78)

# ========================================================================
# SECTION 1: DATA LOADING
# ========================================================================
print("\n[1] Loading data...")
import yfinance as yf


def _flatten(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# --- TLT / VIX / MOVE via yfinance ---
print("  Downloading TLT, VIX, MOVE from yfinance...")
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


# --- FRED yields (DGS10, DGS2, DGS5) ---
def _load_fred(series_id, start, end):
    """Load FRED series from cached CSV if available; else download fresh."""
    cache_path = os.path.join(PROJECT_ROOT, 'storage', 'macro', f'fred_{series_id}.csv')
    if os.path.isfile(cache_path):
        df = pd.read_csv(cache_path)
        df['observation_date'] = pd.to_datetime(df['observation_date'])
        df = df.set_index('observation_date')
        # If cache doesn't cover requested range, fetch fresh
        if df.index[-1] < pd.to_datetime(end) - pd.Timedelta(days=7):
            print(f"    Cache {series_id} stale (last={df.index[-1].date()}); fetching FRED...")
            url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}'
            df = pd.read_csv(url)
            df['observation_date'] = pd.to_datetime(df['observation_date'])
            df = df.set_index('observation_date')
    else:
        print(f"    No cache for {series_id}; fetching FRED...")
        url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}'
        df = pd.read_csv(url)
        df['observation_date'] = pd.to_datetime(df['observation_date'])
        df = df.set_index('observation_date')
    s = df[series_id]
    # FRED uses "." for missing — convert to NaN
    s = pd.to_numeric(s, errors='coerce')
    return s


print("  Loading FRED yields (DGS10, DGS2, DGS5)...")
y10 = _load_fred('DGS10', DATA_START, DATA_END)
y2 = _load_fred('DGS2', DATA_START, DATA_END)
y5 = _load_fred('DGS5', DATA_START, DATA_END)

# Forward-fill weekends/holidays (max 3 days) so yields align with trading dates
y10 = y10.ffill(limit=3)
y2 = y2.ffill(limit=3)
y5 = y5.ffill(limit=3)

# Assemble dataframe
df = pd.DataFrame({
    'price': tlt_px,
    'log_ret': tlt_ret,
    'VIX': vix_close,
    'MOVE': move_close,
    'Y10': y10,
    'Y2': y2,
    'Y5': y5,
}).dropna()

n_total = len(df)
print(f"  Aligned data: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
move = df['MOVE'].values
y10_v = df['Y10'].values           # in percent (e.g., 4.5 = 4.5%)
y2_v = df['Y2'].values
y5_v = df['Y5'].values

# Derived regressors — scaled to be on similar magnitude as VIX (~20) so that
# theta1 bounds (0, 1e-2) can effectively drive tau without hitting boundary.
# A4f squares these before multiplying by theta1; regressor magnitude ~ 10-20
# puts (regressor)^2 ~ 100-400 (same as VIX^2 ~ 400), hence theta1 magnitudes
# will be comparable across models and within bounds.
#
# Y10_v is in percent (e.g., 4.5). |dY10| in percent is tiny (~0.03 = 3 bps).
# Multiply dy by 100 to get units of bps; similarly slope/butterfly kept in
# percent (scale already OK, |slope| ~ 1-3).

dy10_raw = np.concatenate([[0.0], np.diff(y10_v)])  # first day = 0 (no prior)
abs_dy10 = np.abs(dy10_raw) * 100                    # in bps (typical 0-20)
abs_dy10_bps = abs_dy10                              # alias for clarity in buckets

slope_raw = y10_v - y2_v                             # in percent (typical -1 to +3)
abs_slope = np.abs(slope_raw)                        # percent, same scale

butterfly_raw = 2 * y5_v - y2_v - y10_v              # in percent (typical -0.5 to +0.5)
# Scale butterfly by 10 to boost magnitude (small values ~0.1 would yield tiny theta*x^2)
abs_butterfly = np.abs(butterfly_raw) * 10           # now typical 0-5

# Y10 level in percent — already on reasonable scale (1-6 percent)
# We'll use y10_v directly as level regressor

r2 = ret ** 2
dates = df.index


# ========================================================================
# SECTION 2: DIAGNOSTICS
# ========================================================================
print("\n[2] Diagnostics...")
print(f"  TLT ret mean(ann)={np.mean(ret)*252:.4f}, std(ann)={np.std(ret)*np.sqrt(252):.4f}")
print(f"  VIX mean/max: {np.mean(vix):.2f} / {np.max(vix):.2f}")
print(f"  MOVE mean/max: {np.mean(move):.2f} / {np.max(move):.2f}")
print(f"  Y10 mean/max: {np.mean(y10_v):.2f}% / {np.max(y10_v):.2f}%")
print(f"  |dY10| mean/max (bps): {np.mean(abs_dy10_bps):.2f} / {np.max(abs_dy10_bps):.2f}")
print(f"  Slope (10-2) mean: {np.mean(slope_raw):.2f}, min={np.min(slope_raw):.2f}")
print(f"  Butterfly (raw) mean: {np.mean(butterfly_raw):.3f}, std={np.std(butterfly_raw):.3f}")
print(f"  Corr(VIX, MOVE): {np.corrcoef(vix, move)[0,1]:.3f}")
print(f"  Corr(VIX, |dY|): {np.corrcoef(vix, abs_dy10)[0,1]:.3f}")
print(f"  Corr(MOVE, |dY|): {np.corrcoef(move, abs_dy10)[0,1]:.3f}")
print(f"  Corr(TLT r^2, (dY_bps)^2): {np.corrcoef(r2, dy10_raw**2)[0,1]:.3f}")
print(f"  Corr(TLT r^2, VIX^2): {np.corrcoef(r2, vix**2)[0,1]:.3f}")
print(f"  Corr(TLT r^2, MOVE^2): {np.corrcoef(r2, move**2)[0,1]:.3f}")


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
    A4f negative log-likelihood given list of pre-squared, pre-lagged regressor arrays.
    Params: [theta0, theta_1..theta_K, omega_g, alpha, gamma, beta]
    theta_i >= 0 enforced, theta0 free (small bound).
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
    regressor_raw_list: list of arrays (length n) with raw values; we internally lag by 1
    and square. theta_i * x^2 contribution.
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
    means = [np.mean(x) + 1e-10 for x in regs_lagged_sq]

    starts = []
    for scale in [1.0, 0.5, 1.5]:
        theta0 = var0 * 0.05 * scale
        thetas_init = [var0 / (K * m) * scale for m in means]
        starts.append([theta0] + thetas_init + [0.05, 0.05, 0.05, 0.90])

    bounds = [(-1e-2, 1e-2)]  # theta0
    for _ in range(K):
        bounds.append((0.0, 1e-2))  # theta_i >= 0 (sufficiently wide; theta_i scales with 1/E[x^2])
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
    reg_lag_vals: length K list, raw (not squared) values at t-1.
    Returns (sigma2_t, g_new, tau_t).
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
print("\n[4] Out-of-sample forecasting (8 models)...")

# Regressor specification for each A4f variant
# (model_key, list_of_regressor_arrays)
A4F_SPECS = {
    'A4f_VIX':       [vix],
    'A4f_MOVE':      [move],
    'A4f_Level':     [y10_v],                      # 10Y yield level (percent)
    'A4f_Slope':     [abs_slope],                  # |10Y-2Y| in percent
    'A4f_RateVol':   [abs_dy10],                   # |dY10| in bps (realized rate vol)
    'A4f_Butterfly': [abs_butterfly],              # |2*5Y-2Y-10Y| * 10 (scaled)
    'A4f_Combo':     [vix, abs_dy10],              # VIX + |dY10|_bps
}

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

# Forecast storage
forecasts = {k: np.full(n_oos, np.nan) for k in MODEL_KEYS}

refit_log = []
refit_count = 0

# States
gjr_params = None
gjr_h = None
a4f_params = {k: None for k in A4F_SPECS}
a4f_g = {k: None for k in A4F_SPECS}

prev_window = None

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

        # A4f variants
        conv_flags = {'GJR': bool(gjr_conv)}
        theta_samples = {}
        for mkey, regs in A4F_SPECS.items():
            train_regs = [r[train_start:abs_idx] for r in regs]
            p, conv = fit_a4f(train_ret, train_regs)
            conv_flags[mkey] = bool(conv)
            if p is not None:
                a4f_params[mkey] = p
                g_init, _ = init_a4f_state(p, len(regs), train_ret, train_regs)
                a4f_g[mkey] = g_init
                theta_samples[mkey + '_theta1'] = float(p[1])
                if len(regs) > 1:
                    theta_samples[mkey + '_theta2'] = float(p[2])

        refit_log.append({
            'date': dates[abs_idx].strftime('%Y-%m-%d'),
            'window': current_window,
            **{f'conv_{k}': v for k, v in conv_flags.items()},
            **theta_samples,
        })

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx].strftime('%Y-%m-%d')} "
                  f"({current_window}), elapsed {elapsed:.0f}s")

    # Forecasts at day abs_idx
    r_prev = ret[abs_idx - 1]

    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        forecasts['GJR'][t_idx] = h_new
        gjr_h = h_new

    # Lag values for each regressor
    lag_map = {
        'VIX': vix[abs_idx - 1],
        'MOVE': move[abs_idx - 1],
        'Y10': y10_v[abs_idx - 1],
        '|slope|': abs_slope[abs_idx - 1],
        '|dY10|': abs_dy10[abs_idx - 1],
        '|butterfly|': abs_butterfly[abs_idx - 1],
    }
    a4f_lag_lookup = {
        'A4f_VIX':       [lag_map['VIX']],
        'A4f_MOVE':      [lag_map['MOVE']],
        'A4f_Level':     [lag_map['Y10']],
        'A4f_Slope':     [lag_map['|slope|']],
        'A4f_RateVol':   [lag_map['|dY10|']],
        'A4f_Butterfly': [lag_map['|butterfly|']],
        'A4f_Combo':     [lag_map['VIX'], lag_map['|dY10|']],
    }

    for mkey in A4F_SPECS:
        p = a4f_params[mkey]
        g = a4f_g[mkey]
        if p is None:
            continue
        K = len(A4F_SPECS[mkey])
        s2, g_new, _ = a4f_forecast_1step(p, K, a4f_lag_lookup[mkey], r_prev, g)
        forecasts[mkey][t_idx] = s2
        a4f_g[mkey] = g_new

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
oos_absdy_lag = np.empty(n_oos)
oos_y10_lag = np.empty(n_oos)
for i, idx in enumerate(oos_indices):
    j = idx - 1 if idx > 0 else 0
    oos_vix_lag[i] = vix[j]
    oos_move_lag[i] = move[j]
    oos_absdy_lag[i] = abs_dy10_bps[j]  # in bps
    oos_y10_lag[i] = y10_v[j]


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
    arr = arr[np.isfinite(arr)]
    n = len(arr)
    if n < 30:
        return (np.nan, np.nan)
    boot_means = np.empty(n_boot)
    block_len = max(1, int(n**(1/3)))
    for b in range(n_boot):
        starts = rng.integers(0, n, size=(n // block_len + 1))
        blocks = [arr[s:s+block_len] for s in starts if s + block_len <= n]
        if not blocks:
            boot_means[b] = np.mean(arr)
            continue
        boot_sample = np.concatenate(blocks)[:n]
        boot_means[b] = np.mean(boot_sample)
    return (float(np.percentile(boot_means, 2.5)),
            float(np.percentile(boot_means, 97.5)))


# Global valid mask
valid_all = np.ones(n_oos, dtype=bool)
for k in MODEL_KEYS:
    valid_all &= (~np.isnan(forecasts[k]) & (forecasts[k] > 0))
n_valid = valid_all.sum()
print(f"  Valid joint observations (all {len(MODEL_KEYS)} models): {n_valid}/{n_oos}")


def model_stats(fc_arr, r2_arr):
    mask = np.isfinite(fc_arr) & (fc_arr > 0) & np.isfinite(r2_arr)
    fc_arr = fc_arr[mask]
    r2_arr = r2_arr[mask]
    if len(fc_arr) < 10:
        return (np.nan, np.nan)
    ql = qlike_loss(fc_arr, r2_arr)
    rho, _ = stats.spearmanr(fc_arr, r2_arr)
    return float(np.mean(ql)), float(rho)


def dm_vs_gjr(model_key, mask):
    fc_g = forecasts['GJR'][mask]
    fc_m = forecasts[model_key][mask]
    r2_v = oos_r2[mask]
    ql_g = qlike_loss(fc_g, r2_v)
    ql_m = qlike_loss(fc_m, r2_v)
    d = ql_g - ql_m  # positive => model better
    t, p, T = hac_dm_test(d)
    ci = bootstrap_ci_mean_diff(d)
    return t, p, T, ci


def dm_pair(a_key, b_key, mask):
    fc_a = forecasts[a_key][mask]
    fc_b = forecasts[b_key][mask]
    r2_v = oos_r2[mask]
    ql_a = qlike_loss(fc_a, r2_v)
    ql_b = qlike_loss(fc_b, r2_v)
    d = ql_b - ql_a  # positive => A better
    t, p, T = hac_dm_test(d)
    return t, p, T


results = {
    'metadata': {},
    'full_oos': {},
    'per_window': {},
    'crisis_subperiods': {},
    'vix_buckets': {},
    'rate_vol_buckets': {},
    'yield_buckets': {},
    'pairwise_dm': {},
    'refit_log': refit_log,
}

# --- Full OOS ---
if n_valid > 0:
    print(f"\n  FULL OOS (n={n_valid}):")
    print(f"  {'Model':<16} {'QLIKE':>11} {'Spearman':>10} {'DM vs GJR':>10} {'Harvey':>7}")
    full = {}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][valid_all], oos_r2[valid_all])
        if k == 'GJR':
            dm_t, dm_p, T, ci = None, None, int(n_valid), (None, None)
        else:
            dm_t, dm_p, T, ci = dm_vs_gjr(k, valid_all)
        harvey = (dm_t is not None and np.isfinite(dm_t) and abs(dm_t) > 3.0 and dm_t > 0)
        full[k] = {
            'n': int(n_valid),
            'qlike': ql,
            'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
            'dm_p_vs_gjr': float(dm_p) if dm_p is not None and np.isfinite(dm_p) else None,
            'harvey_pass_vs_gjr': bool(harvey),
            'bootstrap_ci_95': [ci[0] if ci[0] is not None else None,
                                ci[1] if ci[1] is not None else None],
        }
        dm_display = f"{dm_t:+.3f}" if dm_t is not None and np.isfinite(dm_t) else "--"
        print(f"  {k:<16} {ql:>11.6f} {rho:>10.3f} {dm_display:>10} "
              f"{'PASS' if harvey else 'FAIL':>7}")
    results['full_oos'] = full

# --- Crisis sub-periods ---
print("\n  Crisis sub-periods (DM t vs GJR):")
header = f"  {'Crisis':<20} {'n':>6} " + " ".join([f"{k.replace('A4f_',''):>10}" for k in MODEL_KEYS if k != 'GJR'])
print(header)
for cname, cstart, cend in CRISIS_PERIODS:
    mask_c = (oos_dates >= cstart) & (oos_dates <= cend) & valid_all
    n_c = mask_c.sum()
    if n_c < 30:
        print(f"  {cname:<20} insufficient (n={n_c})")
        continue
    res_c = {'n': int(n_c), 'start': cstart, 'end': cend}
    dm_row = []
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_c], oos_r2[mask_c])
        if k == 'GJR':
            dm_t = None
        else:
            dm_t, _, _, _ = dm_vs_gjr(k, mask_c)
            dm_row.append(dm_t if dm_t is not None and np.isfinite(dm_t) else np.nan)
        harvey = (dm_t is not None and np.isfinite(dm_t) and abs(dm_t) > 3.0 and dm_t > 0)
        res_c[k] = {
            'qlike': ql,
            'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
            'harvey_pass_vs_gjr': bool(harvey),
        }
    res_c['vix_mean'] = float(np.mean(oos_vix[mask_c]))
    res_c['absdy_mean_bps'] = float(np.mean(oos_absdy_lag[mask_c]))
    print(f"  {cname:<20} {n_c:>6} " +
          " ".join([f"{(x if np.isfinite(x) else 0):>+10.3f}" for x in dm_row]))
    results['crisis_subperiods'][cname] = res_c

# --- VIX buckets (RateVol vs GJR) ---
print("\n  VIX bucket analysis (A4f_RateVol and A4f_Combo vs GJR):")
print(f"  {'Bucket':<14} {'Range':<12} {'n':>6} {'GJR_QL':>11} {'RateVol_QL':>12} {'RV_DM':>8} {'Combo_QL':>11} {'Combo_DM':>9}")
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
            'qlike': ql,
            'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
        }
    ql_gjr = res_b['GJR']['qlike']
    ql_rv = res_b['A4f_RateVol']['qlike']
    ql_co = res_b['A4f_Combo']['qlike']
    rv_dm = res_b['A4f_RateVol']['dm_t_vs_gjr']
    co_dm = res_b['A4f_Combo']['dm_t_vs_gjr']
    print(f"  {bname:<14} [{bmin},{bmax})   {n_b:>6} {ql_gjr:>11.5f} "
          f"{ql_rv:>12.5f} {rv_dm:>+8.3f} {ql_co:>11.5f} {co_dm:>+9.3f}")
    results['vix_buckets'][bname] = res_b

# --- Rate-vol buckets ---
print("\n  Rate-vol bucket analysis (A4f_RateVol vs GJR):")
print(f"  {'Bucket':<18} {'Range bps':<12} {'n':>6} {'GJR_QL':>11} {'RateVol_QL':>12} {'DM':>8}")
for bname, bmin, bmax in RATE_VOL_BUCKETS:
    mask_b = (oos_absdy_lag >= bmin) & (oos_absdy_lag < bmax) & valid_all
    n_b = mask_b.sum()
    if n_b < 20:
        print(f"  {bname:<18} [{bmin},{bmax}) insufficient (n={n_b})")
        results['rate_vol_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    res_b = {'n': int(n_b), 'range': [bmin, bmax]}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_b], oos_r2[mask_b])
        if k == 'GJR':
            dm_t = None
        else:
            dm_t, _, _, _ = dm_vs_gjr(k, mask_b)
        res_b[k] = {
            'qlike': ql,
            'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
        }
    ql_gjr = res_b['GJR']['qlike']
    ql_rv = res_b['A4f_RateVol']['qlike']
    dm = res_b['A4f_RateVol']['dm_t_vs_gjr']
    print(f"  {bname:<18} [{bmin},{bmax})   {n_b:>6} {ql_gjr:>11.5f} "
          f"{ql_rv:>12.5f} {dm:>+8.3f}")
    results['rate_vol_buckets'][bname] = res_b

# --- Yield buckets ---
print("\n  Yield-level bucket analysis (A4f_Level and A4f_RateVol vs GJR):")
print(f"  {'Bucket':<14} {'Range %':<12} {'n':>6} {'GJR_QL':>11} {'Lvl_QL':>11} {'Lvl_DM':>8} {'RV_QL':>11} {'RV_DM':>8}")
for bname, bmin, bmax in YIELD_BUCKETS:
    mask_b = (oos_y10_lag >= bmin) & (oos_y10_lag < bmax) & valid_all
    n_b = mask_b.sum()
    if n_b < 20:
        print(f"  {bname:<14} insufficient (n={n_b})")
        results['yield_buckets'][bname] = {'status': 'insufficient', 'n': int(n_b)}
        continue
    res_b = {'n': int(n_b), 'range': [bmin, bmax]}
    for k in MODEL_KEYS:
        ql, rho = model_stats(forecasts[k][mask_b], oos_r2[mask_b])
        if k == 'GJR':
            dm_t = None
        else:
            dm_t, _, _, _ = dm_vs_gjr(k, mask_b)
        res_b[k] = {
            'qlike': ql,
            'spearman': rho,
            'dm_t_vs_gjr': float(dm_t) if dm_t is not None and np.isfinite(dm_t) else None,
        }
    ql_gjr = res_b['GJR']['qlike']
    ql_l = res_b['A4f_Level']['qlike']
    l_dm = res_b['A4f_Level']['dm_t_vs_gjr']
    ql_r = res_b['A4f_RateVol']['qlike']
    r_dm = res_b['A4f_RateVol']['dm_t_vs_gjr']
    print(f"  {bname:<14} [{bmin},{bmax})   {n_b:>6} {ql_gjr:>11.5f} "
          f"{ql_l:>11.5f} {l_dm:>+8.3f} {ql_r:>11.5f} {r_dm:>+8.3f}")
    results['yield_buckets'][bname] = res_b

# --- Pairwise DM matrix (all models) ---
print("\n  Pairwise DM tests (positive => row model beats column model):")
pair_keys = MODEL_KEYS
n_mods = len(pair_keys)
dm_matrix = np.full((n_mods, n_mods), np.nan)
for i, a in enumerate(pair_keys):
    for j, b in enumerate(pair_keys):
        if i == j:
            dm_matrix[i, j] = 0.0
            continue
        t, p, T = dm_pair(a, b, valid_all)
        dm_matrix[i, j] = t if np.isfinite(t) else np.nan
        if i < j:  # store unique pairs
            key = f"{a}_vs_{b}"
            harvey = np.isfinite(t) and abs(t) > 3.0 and t > 0
            results['pairwise_dm'][key] = {
                'dm_t': float(t) if np.isfinite(t) else None,
                'dm_p': float(p) if np.isfinite(p) else None,
                'n': int(T),
                'harvey_pass': bool(harvey),
            }

# Print a compact pairwise table (Combo/RateVol/Level vs others)
focus = ['A4f_RateVol', 'A4f_Level', 'A4f_Combo']
print(f"  {'vs':<18} " + " ".join([f"{f.replace('A4f_',''):>12}" for f in focus]))
for a in pair_keys:
    if a in focus:
        continue
    cells = []
    for f in focus:
        i = pair_keys.index(f)
        j = pair_keys.index(a)
        cells.append(f"{dm_matrix[i, j]:>+12.3f}" if np.isfinite(dm_matrix[i, j]) else "   --   ")
    print(f"  {a:<18} " + " ".join(cells))


# ========================================================================
# SECTION 6: HYPOTHESIS VERDICTS
# ========================================================================
print("\n" + "=" * 78)
print("HYPOTHESIS VERDICTS")
print("=" * 78)

full = results['full_oos']
def _dm(key):
    v = full.get(key, {}).get('dm_t_vs_gjr') if full else None
    return v

vix_dm = _dm('A4f_VIX')
move_dm = _dm('A4f_MOVE')
lvl_dm = _dm('A4f_Level')
slp_dm = _dm('A4f_Slope')
rv_dm = _dm('A4f_RateVol')
bf_dm = _dm('A4f_Butterfly')
co_dm = _dm('A4f_Combo')

def _pass_hv(t):
    return (t is not None and np.isfinite(t) and abs(t) > 3.0 and t > 0)

# H1: Realized rate vol Harvey-passes
h1_pass = _pass_hv(rv_dm)
# H2: Level or Slope Harvey-passes
h2_pass = _pass_hv(lvl_dm) or _pass_hv(slp_dm)
# H3: Combo beats VIX in pairwise
cv_pair = results['pairwise_dm'].get('A4f_VIX_vs_A4f_Combo', {})
# Positive t means A4f_VIX better; Combo better would be NEGATIVE here
# We look for combo-beats-vix => negate
cv_t = cv_pair.get('dm_t')
h3_pass = (cv_t is not None and np.isfinite(cv_t) and abs(cv_t) > 3.0 and cv_t < 0)

# H4: 2022 rate-hike regime — which factor best captures drawdown
rr22 = results['crisis_subperiods'].get('Rising_Rates_2022', {})
rr22_dms = {k: (rr22.get(k) or {}).get('dm_t_vs_gjr') for k in MODEL_KEYS if k != 'GJR'}
# H4 passes if any yield-curve factor > any option-IV factor in 2022
yc_factors = ['A4f_Level', 'A4f_Slope', 'A4f_RateVol', 'A4f_Butterfly']
iv_factors = ['A4f_VIX', 'A4f_MOVE']
best_yc = max([v for k, v in rr22_dms.items() if k in yc_factors and v is not None], default=-99)
best_iv = max([v for k, v in rr22_dms.items() if k in iv_factors and v is not None], default=-99)
h4_pass = (best_yc > best_iv + 0.5)  # yc meaningfully better than iv

print(f"  H1 (A4f-RateVol Harvey-PASS vs GJR): "
      f"{'PASS' if h1_pass else 'FAIL'}  (t={rv_dm if rv_dm is None else f'{rv_dm:+.3f}'}, need >3)")
print(f"  H2 (A4f-Level or A4f-Slope Harvey-PASS): "
      f"{'PASS' if h2_pass else 'FAIL'}  (Level t={lvl_dm if lvl_dm is None else f'{lvl_dm:+.3f}'}, "
      f"Slope t={slp_dm if slp_dm is None else f'{slp_dm:+.3f}'})")
print(f"  H3 (Combo beats A4f-VIX, Harvey):    "
      f"{'PASS' if h3_pass else 'FAIL'}  (pairwise t={cv_t if cv_t is None else f'{cv_t:+.3f}'})")
print(f"  H4 (yield-curve > option-IV in 2022): "
      f"{'PASS' if h4_pass else 'FAIL'}  (best YC={best_yc:+.3f}, best IV={best_iv:+.3f})")

any_yc_harvey = any(_pass_hv(t) for t in [lvl_dm, slp_dm, rv_dm, bf_dm])
overall_verdict = ('PASS' if any_yc_harvey
                   else ('PARTIAL' if (h4_pass or any(t is not None and t > 1.5
                                                       for t in [lvl_dm, rv_dm, bf_dm, co_dm]))
                         else 'FAIL'))
print(f"\n  OVERALL (bond-matched yield regressor): {overall_verdict}")

results['hypothesis_verdicts'] = {
    'H1_RateVol_harvey': 'PASS' if h1_pass else 'FAIL',
    'H2_LevelOrSlope_harvey': 'PASS' if h2_pass else 'FAIL',
    'H3_Combo_beats_VIX': 'PASS' if h3_pass else 'FAIL',
    'H4_YC_better_in_2022': 'PASS' if h4_pass else 'FAIL',
    'overall': overall_verdict,
}


# ========================================================================
# SECTION 7: METADATA + SAVE
# ========================================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'asset': 'TLT',
    'regressors_tested': ['VIX', 'MOVE', 'Y10', 'Slope', 'RateVol', 'Butterfly', 'VIX+RateVol'],
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
    'rate_vol_buckets': [(n, lo, hi) for n, lo, hi in RATE_VOL_BUCKETS],
    'yield_buckets': [(n, lo, hi) for n, lo, hi in YIELD_BUCKETS],
    'random_seed': 42,
    'elapsed_seconds': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'proposer': 'User (via K1087 brief)',
    'executor': 'Claude',
    'references': [
        'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
        'Patton (2011). J Econometrics 160:246-256.',
        'Harvey, Leybourne & Newbold (2016). t>3.0 threshold.',
        'Litterman & Scheinkman (1991). Common factors in Treasury yields. J Fixed Income 1:54-61.',
        'Balduzzi, Elton & Green (2001). J Financial and Quantitative Analysis 36:523-543.',
        'Chen, Roll & Ross (1986). J Business 59:383-403.',
        'K1075 (SPY A4f-VIX), K1085 (GLD A4f-GVZ), K1086 (TLT A4f-VIX/MOVE NULL).',
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

# Figure 1: Regressor comparison DM matrix (7 models)
fig, ax = plt.subplots(figsize=(10, 5))
model_labels = [k.replace('A4f_', '') for k in MODEL_KEYS if k != 'GJR']
tvals = [results['full_oos'][k]['dm_t_vs_gjr'] for k in MODEL_KEYS if k != 'GJR']
tvals_plot = [t if t is not None and np.isfinite(t) else 0 for t in tvals]
colors = ['#d62728' if (t is not None and np.isfinite(t) and abs(t) > 3.0 and t > 0) else
          ('#2ca02c' if (t is not None and np.isfinite(t) and t > 1.5) else '#1f77b4')
          for t in tvals]
bars = ax.bar(model_labels, tvals_plot, color=colors, alpha=0.85, edgecolor='black')
ax.axhline(3.0, color='red', linestyle='--', label='Harvey |t|=3.0')
ax.axhline(-3.0, color='red', linestyle='--')
ax.axhline(0, color='black', linewidth=0.5)
for bar, t in zip(bars, tvals_plot):
    ax.text(bar.get_x() + bar.get_width()/2, t + (0.1 if t >= 0 else -0.3),
            f'{t:+.2f}', ha='center', fontsize=9)
ax.set_ylabel('DM t-statistic vs GJR (positive = better)')
ax.set_title(f'K1087 TLT: 7 A4f regressor variants vs GJR, Full OOS (n={n_valid})')
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_regressor_comparison.png'), dpi=120)
plt.close()

# Figure 2: Yield-curve time series
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
axes[0].plot(dates, y10_v, color='#1f77b4', linewidth=0.8)
axes[0].plot(dates, y2_v, color='#d62728', linewidth=0.8, alpha=0.7)
axes[0].set_ylabel('Yield (%)')
axes[0].set_title('10Y (blue) and 2Y (red) Treasury Yields')
axes[0].grid(alpha=0.3)

axes[1].plot(dates, slope_raw, color='#2ca02c', linewidth=0.8)
axes[1].axhline(0, color='black', linewidth=0.5, linestyle='--')
axes[1].set_ylabel('Slope (%)')
axes[1].set_title('Yield-Curve Slope (10Y - 2Y) — negative = inverted')
axes[1].grid(alpha=0.3)

axes[2].plot(dates, abs_dy10_bps, color='#9467bd', linewidth=0.5)
axes[2].set_ylabel('|ΔY_10Y| (bps)')
axes[2].set_title('Daily |10Y change| (realized rate vol proxy)')
axes[2].grid(alpha=0.3)
axes[2].set_xlabel('Date')

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_yield_curve.png'), dpi=120)
plt.close()

# Figure 3: 2022 rate-hike period analysis
# Note: use df['price'] for correctly-aligned TLT series
tlt_px_aligned = df['price'].values
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
mask_2022 = (dates >= '2022-01-01') & (dates <= '2022-12-31')
axes[0].plot(dates[mask_2022], tlt_px_aligned[mask_2022], color='black', linewidth=1)
axes[0].set_ylabel('TLT price')
axes[0].set_title('TLT during 2022 rising-rate regime')
axes[0].grid(alpha=0.3)

axes[1].plot(dates[mask_2022], y10_v[mask_2022], color='#1f77b4', label='10Y yield (%)')
ax2b = axes[1].twinx()
ax2b.plot(dates[mask_2022], abs_dy10_bps[mask_2022], color='#d62728', alpha=0.5,
          label='|ΔY| (bps)', linewidth=0.7)
axes[1].set_ylabel('10Y yield (%)', color='#1f77b4')
ax2b.set_ylabel('|ΔY| (bps)', color='#d62728')
axes[1].set_title('Yield level and realized rate vol')
axes[1].grid(alpha=0.3)
axes[1].set_xlabel('Date')

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_2022_rate_hike.png'), dpi=120)
plt.close()

# Figure 4: theta1 stability across refits
fig, axes = plt.subplots(len([k for k in MODEL_KEYS if k != 'GJR']), 1,
                          figsize=(11, 14), sharex=True)
rl_dates = [datetime.strptime(r['date'], '%Y-%m-%d') for r in refit_log]
for ax_i, mkey in enumerate([k for k in MODEL_KEYS if k != 'GJR']):
    theta_key = mkey + '_theta1'
    thetas = [r.get(theta_key) for r in refit_log]
    axes[ax_i].plot(rl_dates, thetas, 'o-', markersize=4, color='#1f77b4', alpha=0.8)
    axes[ax_i].set_ylabel(f'θ1 ({mkey})')
    axes[ax_i].grid(alpha=0.3)
axes[-1].set_xlabel('Refit date')
axes[0].set_title('K1087 TLT: θ1 evolution across refits (seed=42, W=2000, 63d refit)')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_theta1_compare.png'), dpi=120)
plt.close()

# Figure 5: Asset-class × regressor final matrix
# Rows: Equity(SPY), Gold(GLD), Bond(TLT)
# Cols: VIX, GVZ, MOVE, Yield-Level, |ΔY| (RateVol), Combo
fig, ax = plt.subplots(figsize=(10, 4.5))
asset_rows = ['Equity (SPY)', 'Gold (GLD)', 'Bond (TLT)']
col_labels = ['VIX', 'GVZ', 'MOVE', 'Y10 Level', '|ΔY| RateVol', 'Combo']

# SPY: K1075 A4f-VIX ~ 4.48, others n/a
# GLD: K1085 A4f-VIX=1.83, A4f-GVZ=4.46, others n/a
# TLT: K1086 VIX/MOVE, K1087 Level/RateVol/Combo
tlt_vix = vix_dm if vix_dm is not None else np.nan
tlt_move = move_dm if move_dm is not None else np.nan
tlt_lvl = lvl_dm if lvl_dm is not None else np.nan
tlt_rv = rv_dm if rv_dm is not None else np.nan
tlt_combo = co_dm if co_dm is not None else np.nan
matrix = np.array([
    [4.48, np.nan, np.nan, np.nan, np.nan, np.nan],
    [1.83, 4.46, np.nan, np.nan, np.nan, np.nan],
    [tlt_vix, np.nan, tlt_move, tlt_lvl, tlt_rv, tlt_combo],
])
im = ax.imshow(matrix, cmap='RdYlGn', vmin=-5, vmax=5, aspect='auto')
ax.set_xticks(np.arange(len(col_labels)))
ax.set_xticklabels(col_labels, rotation=20, ha='right')
ax.set_yticks(np.arange(len(asset_rows)))
ax.set_yticklabels(asset_rows)
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if np.isnan(val):
            ax.text(j, i, 'n/a', ha='center', va='center', color='gray', fontsize=9)
        else:
            ax.text(j, i, f'{val:+.2f}', ha='center', va='center',
                    color='black', fontsize=10, fontweight='bold')
ax.set_title('Asset-matched regressor theory: A4f DM t vs GJR\n'
             '(K1075 SPY + K1085 GLD + K1086 TLT IV + K1087 TLT yield-curve)')
plt.colorbar(im, ax=ax, label='DM t-stat')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_asset_class_final.png'), dpi=120)
plt.close()

print("  Saved 5 figures: k1087_regressor_comparison.png, k1087_yield_curve.png, "
      "k1087_2022_rate_hike.png, k1087_theta1_compare.png, k1087_asset_class_final.png")
print(f"\n{EXPERIMENT_ID} COMPLETE. Total time: {time.time() - START_TIME:.0f}s")
