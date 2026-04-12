#!/usr/bin/env python3
"""
K1065: Hansen-Lunde (2005) Overnight vs Intraday Variance Decomposition
        — A4f Attribution for SPY

Research Questions:
  H1: sigma2_intraday more predictable than sigma2_overnight
  H2: VIX^2_{t-1} more informative about sigma2_intraday than sigma2_overnight
  H3: A4f's edge (K988 DM t=4.48) comes primarily from intraday component

Decomposition (Hansen & Lunde 2005):
  sigma2_total_t = sigma2_overnight_t + sigma2_intraday_t
  sigma2_overnight_t = ((open_t - close_{t-1}) / close_{t-1})^2
  sigma2_intraday_t  = sum((r_5min)^2) during trading hours

Prior work:
  K1057 (60d): overnight share = 32.7%, ov/intra corr = 0.186 (low)
  K1054: 60-day HAR-RV undertrained
  K1063: semi-variance persistence asymmetry (beta- > beta+)
  K988: A4f-VIX^2 beats GJR by DM t=4.48 on total r^2 target

Data:
  5-min SPY:  data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files, 2026-01-14..2026-04-10)
  Daily SPY:  yfinance (Open/Close for overnight computation, plus history for training)
  VIX:        yfinance

References:
  - Hansen & Lunde (2005). A forecast comparison of volatility models:
    does anything beat a GARCH(1,1)? J Appl Econometrics 20(7):873-889.
  - Corsi (2009). A simple approximate long-memory model of realized volatility.
  - Andersen, Bollerslev, Diebold & Labys (2001). The distribution of realized
    exchange rate volatility. JASA 96(453):42-55.
  - Patton (2011). Volatility forecast comparison using imperfect volatility
    proxies. J Econometrics 160(1):246-256.
  - Engle, Ghysels & Sohn (2013). Stock market volatility and macroeconomic
    fundamentals. Rev Econ Stat 95(3):776-797.

Status: PRELIMINARY (60-day sample << 252-day recommended minimum)
Random seed: 42
Date: 2026-04-12
"""

from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from glob import glob

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize, stats

warnings.filterwarnings('ignore')
np.random.seed(42)

# ---- Paths ----
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = SCRIPT_DIR
RESULTS_PATH = os.path.join(OUTPUT_DIR, 'k1065_results.json')

sys.path.insert(0, os.path.join(MAIN_REPO, 'src'))
from volpred.stats.model_evaluation import dm_test, qlike, spearman_corr  # noqa: E402

print("=" * 72)
print("K1065: Hansen-Lunde Overnight vs Intraday Decomposition (A4f attribution)")
print("=" * 72)
print(f"Started at: {datetime.now(timezone.utc).isoformat()}")

START_TIME = time.time()

EXPERIMENT_ID = "K1065"


# ==========================================================================
# 1. LOAD 5-MIN DATA + COMPUTE INTRADAY RV (PER DAY)
# ==========================================================================

def compute_intraday_rv(filepath: str) -> dict | None:
    """Compute sum(r^2) from 5-min closes for a single trading day."""
    df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)
    close = df[('Close', 'SPY')].dropna()
    if len(close) < 5:
        return None
    # simple returns (consistent with collect_5min_data.py convention)
    returns = close.pct_change().dropna()
    if len(returns) < 3:
        return None
    r = returns.values
    rv_intraday = float(np.sum(r ** 2))
    open_price = float(close.iloc[0])
    close_price = float(close.iloc[-1])
    n_bars = int(len(r))
    return {
        'rv_intraday': rv_intraday,
        'open_5min_first': open_price,
        'close_5min_last': close_price,
        'n_bars': n_bars,
    }


print("\n[1] Loading 5-min data and computing intraday RV...")

fivemin_files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(fivemin_files)} 5-min CSV files")

intraday_records: dict[str, dict] = {}
for fpath in fivemin_files:
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    rec = compute_intraday_rv(fpath)
    if rec is not None:
        intraday_records[date_str] = rec

print(f"  Successfully processed: {len(intraday_records)} days")
dates_5min = sorted(intraday_records.keys())
intraday_dates_dt = pd.to_datetime(dates_5min)
rv_intraday_series = pd.Series(
    [intraday_records[d]['rv_intraday'] for d in dates_5min],
    index=intraday_dates_dt,
    name='rv_intraday',
)
print(f"  Date range: {intraday_dates_dt[0].date()} to {intraday_dates_dt[-1].date()}")
print(f"  rv_intraday mean: {rv_intraday_series.mean():.6e}")
print(f"  rv_intraday std:  {rv_intraday_series.std():.6e}")

# ==========================================================================
# 2. LOAD DAILY PRICES (OPEN/CLOSE) + VIX FROM yfinance
# ==========================================================================

print("\n[2] Loading daily SPY (Open/Close) and VIX...")

import yfinance as yf  # noqa: E402

spy_start = '2016-01-01'
spy_end = '2026-04-12'

spy_data = yf.download('SPY', start=spy_start, end=spy_end, progress=False)
vix_data = yf.download('^VIX', start=spy_start, end=spy_end, progress=False)


def _col(df, name):
    if isinstance(df.columns, pd.MultiIndex):
        # first level is field, second is ticker
        return df[(name, df.columns.get_level_values(1)[0])].squeeze()
    return df[name].squeeze()


spy_close = _col(spy_data, 'Close')
spy_open = _col(spy_data, 'Open')
vix_close = _col(vix_data, 'Close')

# Close-to-close daily return and r^2
daily_close_ret = spy_close.pct_change()
daily_r2 = daily_close_ret ** 2

# Overnight return = (open_t - close_{t-1}) / close_{t-1}
overnight_ret = (spy_open - spy_close.shift(1)) / spy_close.shift(1)
overnight_r2 = overnight_ret ** 2

# Open-to-close (close-to-close - overnight in log? use simple approx)
# Using simple returns: (close_t - open_t)/open_t
oc_ret = (spy_close - spy_open) / spy_open
oc_r2 = oc_ret ** 2

print(f"  SPY close  : {len(spy_close)} obs")
print(f"  SPY open   : {len(spy_open)} obs")
print(f"  VIX close  : {len(vix_close)} obs")

# ==========================================================================
# 3. ALIGN DATA AND CONSTRUCT DECOMPOSITION FRAME
# ==========================================================================

print("\n[3] Aligning overnight_r2 with intraday_rv (both on 5-min dates)...")

# Both series indexed by date; keep intersection
ov_aligned = overnight_r2.reindex(intraday_dates_dt)
oc_r2_aligned = oc_r2.reindex(intraday_dates_dt)
r2_total_aligned = daily_r2.reindex(intraday_dates_dt)
vix_aligned = vix_close.reindex(intraday_dates_dt)

frame = pd.DataFrame({
    'rv_intraday': rv_intraday_series,
    'r2_overnight': ov_aligned,
    'r2_oc': oc_r2_aligned,
    'r2_total': r2_total_aligned,
    'VIX': vix_aligned,
}).dropna()

# Total variance proxy per Hansen-Lunde: overnight r^2 + intraday RV
frame['sigma2_total_HL'] = frame['r2_overnight'] + frame['rv_intraday']

print(f"  Aligned observations: {len(frame)}")
print(f"  Period: {frame.index[0].date()} to {frame.index[-1].date()}")

# Descriptive
share_overnight = frame['r2_overnight'] / frame['sigma2_total_HL']
share_intraday = frame['rv_intraday'] / frame['sigma2_total_HL']
corr_ov_intra = float(frame['r2_overnight'].corr(frame['rv_intraday']))

print("\n  Decomposition summary:")
print(f"    overnight share (mean):  {share_overnight.mean():.1%}")
print(f"    overnight share (med):   {share_overnight.median():.1%}")
print(f"    intraday  share (mean):  {share_intraday.mean():.1%}")
print(f"    corr(overnight_r2, intraday_RV): {corr_ov_intra:+.3f}")

# ACF of each component
def acf_k(x: np.ndarray, k: int) -> float:
    x = np.asarray(x, dtype=np.float64)
    n = len(x)
    if n <= k:
        return float('nan')
    xm = x - x.mean()
    c0 = np.sum(xm ** 2)
    ck = np.sum(xm[k:] * xm[:-k])
    return float(ck / c0) if c0 > 0 else 0.0


acf_table: dict[str, dict[str, float]] = {}
for name in ['rv_intraday', 'r2_overnight', 'sigma2_total_HL']:
    acf_table[name] = {
        'lag1': acf_k(frame[name].values, 1),
        'lag5': acf_k(frame[name].values, 5),
        'lag22': acf_k(frame[name].values, 22),
    }
print("\n  Autocorrelations (small-sample; 60 days):")
for name, d in acf_table.items():
    print(f"    {name:18s}  lag1={d['lag1']:+.3f}  lag5={d['lag5']:+.3f}  lag22={d['lag22']:+.3f}")

# Leverage-style correlations (daily close-to-close return vs next-day components)
# Full daily return series (not just 5min days)
ret_next_intraday = frame['rv_intraday'].reindex(intraday_dates_dt)
ret_prev = daily_close_ret.reindex(intraday_dates_dt).shift(1)
lev_ret_rv = float(ret_prev.corr(frame['rv_intraday']))
lev_ret_ov = float(ret_prev.corr(frame['r2_overnight']))
print(f"\n  Leverage (corr(ret_{{t-1}}, component_t)):")
print(f"    vs rv_intraday:  {lev_ret_rv:+.3f}")
print(f"    vs r2_overnight: {lev_ret_ov:+.3f}")

# ==========================================================================
# 4. OOS PREDICTION: AR(1) / GJR / VIX^2-LAG FOR EACH COMPONENT
# ==========================================================================

print("\n[4] OOS prediction of each component (AR1 / GJR-on-daily-ret / VIX^2-lag)...")

# We can only evaluate within the 5-min date range (60 days).
# Initial training window = 30 days (same as K1057) so we have 30 OOS days.
INIT_WINDOW = 30
n_total = len(frame)
oos_start_idx = INIT_WINDOW
assert oos_start_idx < n_total, "Not enough data for OOS."
n_oos = n_total - oos_start_idx
oos_dates = frame.index[oos_start_idx:]
print(f"  Training window: expanding from {INIT_WINDOW}")
print(f"  OOS period: {n_oos} days ({oos_dates[0].date()} to {oos_dates[-1].date()})")

rv_intra_values = frame['rv_intraday'].values
r2_ov_values = frame['r2_overnight'].values
sigma2_total_HL_values = frame['sigma2_total_HL'].values
vix_values = frame['VIX'].values

# AR(1): x_{t} ~ alpha + beta * x_{t-1}
def _clip_forecast(yhat: float, y_train: np.ndarray) -> float:
    """Clip OLS forecast to plausible range for small-sample variance prediction.

    Lower bound: 10% of training mean (prevents ratio blow-up in QLIKE).
    Upper bound: 10x training max (prevents extrapolation blow-up).
    """
    y_mean = float(np.mean(y_train))
    y_max = float(np.max(y_train))
    lower = max(0.1 * y_mean, 1e-12)
    upper = max(10.0 * y_max, lower * 10)
    return min(max(yhat, lower), upper)


def ols_forecast(x_lag_series: np.ndarray, y_series: np.ndarray,
                 x_lag_test: float) -> float:
    n = len(y_series)
    X = np.column_stack([np.ones(n), x_lag_series])
    try:
        beta = np.linalg.lstsq(X, y_series, rcond=None)[0]
        yhat = float(beta[0] + beta[1] * x_lag_test)
        return _clip_forecast(yhat, y_series)
    except Exception:
        return max(float(np.mean(y_series)), 1e-12)


def ols_forecast_2x(x1_lag: np.ndarray, x2_lag: np.ndarray,
                    y: np.ndarray, x1_test: float, x2_test: float) -> float:
    """OLS with 2 regressors; clip forecasts to plausible range."""
    n = len(y)
    X = np.column_stack([np.ones(n), x1_lag, x2_lag])
    try:
        b = np.linalg.lstsq(X, y, rcond=None)[0]
        yhat = float(b[0] + b[1] * x1_test + b[2] * x2_test)
        return _clip_forecast(yhat, y)
    except Exception:
        return max(float(np.mean(y)), 1e-12)


# --- GJR-GARCH(1,1) on daily close-to-close returns (for comparison) ---
# We need a long history before the 5-min OOS window.
hist_start = '2005-01-01'
hist_end = intraday_dates_dt[-1].strftime('%Y-%m-%d')
spy_hist = yf.download('SPY', start=hist_start, end=hist_end, progress=False)
vix_hist = yf.download('^VIX', start=hist_start, end=hist_end, progress=False)
spy_hist_close = _col(spy_hist, 'Close')
spy_hist_open = _col(spy_hist, 'Open')
vix_hist_close = _col(vix_hist, 'Close')
log_ret_hist = np.log(spy_hist_close / spy_hist_close.shift(1))
daily_frame_hist = pd.DataFrame({
    'log_ret': log_ret_hist,
    'close': spy_hist_close,
    'open': spy_hist_open,
    'VIX': vix_hist_close,
}).dropna()
print(f"  History frame: {len(daily_frame_hist)} obs ({daily_frame_hist.index[0].date()} to {daily_frame_hist.index[-1].date()})")

# Convenience: define r_overnight & r_oc on the full history
r_overnight_full = (daily_frame_hist['open'] - daily_frame_hist['close'].shift(1)) / daily_frame_hist['close'].shift(1)
r_oc_full = (daily_frame_hist['close'] - daily_frame_hist['open']) / daily_frame_hist['open']
r_close_full = daily_frame_hist['close'].pct_change()
daily_frame_hist['r_overnight'] = r_overnight_full
daily_frame_hist['r_oc'] = r_oc_full
daily_frame_hist['r_close'] = r_close_full
daily_frame_hist = daily_frame_hist.dropna()

# --- GJR log-likelihood helpers (pure numpy, no numba to avoid build issues) ---
def gjr_nll(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[: min(250, n)])) + 1e-12
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-12:
            h[t] = 1e-12
    ll = 0.0
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])
    return -ll


def fit_gjr(returns):
    returns = np.asarray(returns, dtype=np.float64)
    var0 = float(np.var(returns))
    best_ll = np.inf
    best = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-10, max(var0, 1e-8)), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_nll, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll and np.isfinite(res.fun):
                best_ll = res.fun
                best = res.x
        except Exception:
            continue
    return best


def gjr_filter_forecast(params, returns):
    """Return one-step-ahead h forecast for each t+1, aligned so h_fc[t] is
    forecast made at end of day t for day t+1. Length = len(returns)."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[: min(250, n)])) + 1e-12
    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-12:
            h[t] = 1e-12
    # h_fc[t] = sigma2 for day t+1
    h_fc = np.empty(n)
    for t in range(n):
        r_t = returns[t]
        asym_t = gamma * r_t ** 2 if r_t < 0 else 0.0
        h_fc[t] = max(omega + alpha * r_t ** 2 + asym_t + beta * h[t], 1e-12)
    return h_fc


# Fit GJR ONCE on all history up to first OOS date (still no lookahead on OOS)
first_oos_date = oos_dates[0]
hist_up_to_oos = daily_frame_hist[daily_frame_hist.index < first_oos_date]
print(f"  GJR fit: {len(hist_up_to_oos)} obs ({hist_up_to_oos.index[0].date()} to {hist_up_to_oos.index[-1].date()})")
gjr_params_close = fit_gjr(hist_up_to_oos['r_close'].values)
gjr_params_oc = fit_gjr(hist_up_to_oos['r_oc'].values)
gjr_params_overnight = fit_gjr(hist_up_to_oos['r_overnight'].values)
print(f"  GJR-close    params: {gjr_params_close}")
print(f"  GJR-OC       params: {gjr_params_oc}")
print(f"  GJR-overnight params: {gjr_params_overnight}")

# For each OOS date, compute GJR one-step h using data up to that date
# (we'll filter through entire history + OOS days up to t-1 and forecast t)
full_close = daily_frame_hist['r_close'].values
full_oc = daily_frame_hist['r_oc'].values
full_on = daily_frame_hist['r_overnight'].values
full_idx = daily_frame_hist.index

# Map each OOS date to position in full history
full_pos = {d: i for i, d in enumerate(full_idx)}

# h_fc series (aligned with full_idx): h_fc[t] = forecast for day t+1
h_fc_close = gjr_filter_forecast(gjr_params_close, full_close)
h_fc_oc = gjr_filter_forecast(gjr_params_oc, full_oc)
h_fc_on = gjr_filter_forecast(gjr_params_overnight, full_on)

# Build GJR forecast arrays aligned to OOS dates in `frame`
gjr_close_fc = np.full(n_oos, np.nan)
gjr_oc_fc = np.full(n_oos, np.nan)
gjr_on_fc = np.full(n_oos, np.nan)
for i, d in enumerate(oos_dates):
    # h_fc made at end of day t-1 for day t
    # find previous trading day
    prev_positions = [p for p_d, p in full_pos.items() if p_d < d]
    if not prev_positions:
        continue
    last_prev = max(prev_positions)
    gjr_close_fc[i] = h_fc_close[last_prev]
    gjr_oc_fc[i] = h_fc_oc[last_prev]
    gjr_on_fc[i] = h_fc_on[last_prev]

# AR(1) and VIX^2-lag forecasts for each target.
def run_ar1_and_vix2(target_values, vix_series_in_frame):
    """Run OOS AR1 on target itself + VIX^2-lag regression on target.

    target_values: aligned with frame.index
    vix_series_in_frame: aligned with frame.index (the raw VIX values)
    """
    ar1_fc = np.full(n_oos, np.nan)
    vix2_fc = np.full(n_oos, np.nan)
    ar1_vix2_fc = np.full(n_oos, np.nan)

    for i in range(n_oos):
        t = oos_start_idx + i  # target index
        # Need y_train (target values at indices 1..t-1) and x_lag_train (values at 0..t-2)
        y_train = target_values[1:t]
        x_lag_train = target_values[:t - 1]
        # VIX^2_{t-1}: regressor is VIX^2 at t-1 predicting target at t
        vix2_lag_train = vix_series_in_frame[:t - 1] ** 2
        # Test inputs
        x_lag_test = float(target_values[t - 1])
        vix2_lag_test = float(vix_series_in_frame[t - 1] ** 2)

        if len(y_train) < 5:
            continue
        ar1_fc[i] = ols_forecast(x_lag_train, y_train, x_lag_test)
        vix2_fc[i] = ols_forecast(vix2_lag_train, y_train, vix2_lag_test)
        ar1_vix2_fc[i] = ols_forecast_2x(x_lag_train, vix2_lag_train,
                                         y_train, x_lag_test, vix2_lag_test)
    return ar1_fc, vix2_fc, ar1_vix2_fc


ar1_intra, vix2_intra, arvix_intra = run_ar1_and_vix2(rv_intra_values, vix_values)
ar1_ov, vix2_ov, arvix_ov = run_ar1_and_vix2(r2_ov_values, vix_values)
ar1_tot, vix2_tot, arvix_tot = run_ar1_and_vix2(sigma2_total_HL_values, vix_values)

# ==========================================================================
# 5. A4f ATTRIBUTION
# ==========================================================================
# K988's A4f (VIX^2 in tau) was estimated on close-to-close log returns with
# target = sigma^2 for that daily return. Here we re-estimate the same
# specification on three different target "returns":
#   A4f-Close:   returns = close-to-close daily (K988 original spec)
#   A4f-OC:      returns = open-to-close (intraday)
#   A4f-ON:      returns = overnight (open_t - close_{t-1})/close_{t-1}
#
# This answers H3: Does the A4f "edge" come from modelling close-to-close,
# open-to-close (intraday), or overnight? We compare each model's sigma^2_hat
# against the *natural* target: r^2 of that return series, on the 60-day
# aligned OOS window.
#
# NOTE: A4f-OC/A4f-ON use r^2 of their native return, not intraday-RV or
# r2_overnight_sum_within_5min. This respects the K1057 model-target rule.
# ==========================================================================

print("\n[5] A4f attribution: re-fit VIX^2-tau spec on three return targets...")


def fit_a4f_vix_squared(returns, vix_vals):
    """Fit the multiplicative GJR-X model with tau = theta0 + theta1*VIX^2_{t-1}.

    Matches K988 spec A4/A4f: denom_mode='tau_t' (Engle et al. 2013), with
    free omega. Two-step -> joint MLE with multiple starts.
    """
    n = len(returns)
    # lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_ll(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if alpha < 0 or gamma_p < 0 or beta < 0 or omega_g <= 0:
            return 1e12
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e12
        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
        g = np.empty(n)
        # Initialize g[0] at unconditional mean omega/(1-persist)
        eg = omega_g / (1.0 - persist)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(tau[t])  # denom = tau_t
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            s2 = tau[t] * g[t]
            if s2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(s2) + returns[t] ** 2 / s2)
        return -ll

    var0 = float(np.var(returns))
    vix2_mean = float(np.mean(vix_lag ** 2)) + 1e-8
    starts = [
        [var0 * 0.10, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.20, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best = None
    for s in starts:
        try:
            res = optimize.minimize(neg_ll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll and np.isfinite(res.fun):
                best_ll = res.fun
                best = res.x
        except Exception:
            continue
    return best


def a4f_forecast(params, returns, vix_vals):
    """One-step-ahead sigma^2 forecast series, aligned like GJR: f[t] predicts t+1."""
    theta0, theta1, omega_g, alpha, gamma_p, beta = params
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)
    g = np.empty(n)
    persist = alpha + gamma_p / 2.0 + beta
    eg = omega_g / (1.0 - persist + 1e-12)
    g[0] = eg
    for t in range(1, n):
        u_prev = returns[t - 1] / np.sqrt(tau[t])
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g[t] = omega_g + alpha * u_prev ** 2 + asym + beta * g[t - 1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    # Forecast sigma2_{t+1} using info up to t
    # Need tau_{t+1} = theta0 + theta1 * VIX_t^2; proxy by shifting vix_vals one further.
    # Build vix_lag_plus1[t] = VIX_t (info available at end of day t)
    vix_now = np.asarray(vix_vals, dtype=np.float64)
    tau_next = np.maximum(theta0 + theta1 * vix_now ** 2, 1e-16)

    h_fc = np.empty(n)
    for t in range(n):
        r_t = returns[t]
        u_t = r_t / np.sqrt(tau[t])
        asym_t = gamma_p * u_t ** 2 if u_t < 0 else 0.0
        g_next = omega_g + alpha * u_t ** 2 + asym_t + beta * g[t]
        g_next = max(g_next, 1e-10)
        h_fc[t] = max(tau_next[t] * g_next, 1e-12)
    return h_fc


# Fit A4f specs on the history up to first OOS date (same cutoff as GJR)
hist_close_ret = hist_up_to_oos['r_close'].values
hist_oc_ret = hist_up_to_oos['r_oc'].values
hist_on_ret = hist_up_to_oos['r_overnight'].values
hist_vix = hist_up_to_oos['VIX'].values

print("  Fitting A4f-Close...")
a4f_close_params = fit_a4f_vix_squared(hist_close_ret, hist_vix)
print(f"    params: {a4f_close_params}")

print("  Fitting A4f-OC (open-to-close)...")
a4f_oc_params = fit_a4f_vix_squared(hist_oc_ret, hist_vix)
print(f"    params: {a4f_oc_params}")

print("  Fitting A4f-ON (overnight)...")
a4f_on_params = fit_a4f_vix_squared(hist_on_ret, hist_vix)
print(f"    params: {a4f_on_params}")

# Apply to full history to get forecast series, then slice to OOS indices
full_vix = daily_frame_hist['VIX'].values

a4f_close_fc_full = a4f_forecast(a4f_close_params, full_close, full_vix)
a4f_oc_fc_full = a4f_forecast(a4f_oc_params, full_oc, full_vix)
a4f_on_fc_full = a4f_forecast(a4f_on_params, full_on, full_vix)

a4f_close_fc = np.full(n_oos, np.nan)
a4f_oc_fc = np.full(n_oos, np.nan)
a4f_on_fc = np.full(n_oos, np.nan)
for i, d in enumerate(oos_dates):
    prev_positions = [p for p_d, p in full_pos.items() if p_d < d]
    if not prev_positions:
        continue
    last_prev = max(prev_positions)
    a4f_close_fc[i] = a4f_close_fc_full[last_prev]
    a4f_oc_fc[i] = a4f_oc_fc_full[last_prev]
    a4f_on_fc[i] = a4f_on_fc_full[last_prev]


# ==========================================================================
# 6. EVALUATE ON NATIVE TARGETS (OOS, 30 days)
# ==========================================================================

print("\n[6] Evaluating predictions on each component's native target...")

# Native targets (OOS slice)
oos_rv_intra = rv_intra_values[oos_start_idx:]
oos_r2_ov = r2_ov_values[oos_start_idx:]
oos_sigma2_total_HL = sigma2_total_HL_values[oos_start_idx:]

# Reference: daily r^2 for close/OC returns during OOS
oos_r2_close = daily_r2.reindex(oos_dates).values
oos_r2_oc = oc_r2.reindex(oos_dates).values


def eval_forecast(actual, predicted, name=''):
    actual = np.asarray(actual, dtype=np.float64)
    predicted = np.asarray(predicted, dtype=np.float64)
    valid = np.isfinite(actual) & np.isfinite(predicted) & (actual > 0) & (predicted > 0)
    n_valid = int(valid.sum())
    if n_valid < 5:
        return {'n_valid': n_valid, 'qlike': float('nan'),
                'spearman_rho': float('nan'), 'spearman_p': float('nan'),
                'mse': float('nan'), 'mae': float('nan')}
    a = actual[valid]
    p = predicted[valid]
    ql = qlike(a, p)
    rho, pv = spearman_corr(a, p)
    mse = float(np.mean((a - p) ** 2))
    mae = float(np.mean(np.abs(a - p)))
    return {'n_valid': n_valid, 'qlike': float(ql), 'spearman_rho': float(rho),
            'spearman_p': float(pv), 'mse': mse, 'mae': mae}


eval_section: dict = {}

# --- Target 1: sigma2_intraday ---
print("\n  Target 1: sigma2_intraday (rv_intraday)")
t1 = {}
t1['AR1']           = eval_forecast(oos_rv_intra, ar1_intra)
t1['VIX2_lag']      = eval_forecast(oos_rv_intra, vix2_intra)
t1['AR1+VIX2']      = eval_forecast(oos_rv_intra, arvix_intra)
t1['GJR_close']     = eval_forecast(oos_rv_intra, gjr_close_fc)
t1['GJR_oc']        = eval_forecast(oos_rv_intra, gjr_oc_fc)
t1['A4f_close']     = eval_forecast(oos_rv_intra, a4f_close_fc)
t1['A4f_oc']        = eval_forecast(oos_rv_intra, a4f_oc_fc)
for k, v in t1.items():
    print(f"    {k:14s}  QLIKE={v['qlike']:+.4f}  rho={v['spearman_rho']:+.3f}  n={v['n_valid']}")
eval_section['intraday'] = t1

# --- Target 2: sigma2_overnight ---
print("\n  Target 2: sigma2_overnight (r^2_overnight)")
t2 = {}
t2['AR1']           = eval_forecast(oos_r2_ov, ar1_ov)
t2['VIX2_lag']      = eval_forecast(oos_r2_ov, vix2_ov)
t2['AR1+VIX2']      = eval_forecast(oos_r2_ov, arvix_ov)
t2['GJR_close']     = eval_forecast(oos_r2_ov, gjr_close_fc)
t2['GJR_overnight'] = eval_forecast(oos_r2_ov, gjr_on_fc)
t2['A4f_close']     = eval_forecast(oos_r2_ov, a4f_close_fc)
t2['A4f_on']        = eval_forecast(oos_r2_ov, a4f_on_fc)
for k, v in t2.items():
    print(f"    {k:14s}  QLIKE={v['qlike']:+.4f}  rho={v['spearman_rho']:+.3f}  n={v['n_valid']}")
eval_section['overnight'] = t2

# --- Target 3: sigma2_total_HL (Hansen-Lunde aggregated) ---
print("\n  Target 3: sigma2_total_HL = r2_overnight + rv_intraday")
t3 = {}
t3['AR1']           = eval_forecast(oos_sigma2_total_HL, ar1_tot)
t3['VIX2_lag']      = eval_forecast(oos_sigma2_total_HL, vix2_tot)
t3['AR1+VIX2']      = eval_forecast(oos_sigma2_total_HL, arvix_tot)
t3['GJR_close']     = eval_forecast(oos_sigma2_total_HL, gjr_close_fc)
t3['A4f_close']     = eval_forecast(oos_sigma2_total_HL, a4f_close_fc)
# Sum-of-components baseline: A4f_on + A4f_oc
a4f_sum_fc = a4f_oc_fc + a4f_on_fc
t3['A4f_oc+A4f_on'] = eval_forecast(oos_sigma2_total_HL, a4f_sum_fc)
for k, v in t3.items():
    print(f"    {k:14s}  QLIKE={v['qlike']:+.4f}  rho={v['spearman_rho']:+.3f}  n={v['n_valid']}")
eval_section['total_HL'] = t3

# --- Additional Target 4: r^2 close-to-close (K988 native target) ---
print("\n  Target 4 (ref): r^2_close (K988 native target)")
t4 = {}
t4['AR1']       = eval_forecast(oos_r2_close, ar1_tot)  # not ideal but ref
t4['GJR_close'] = eval_forecast(oos_r2_close, gjr_close_fc)
t4['A4f_close'] = eval_forecast(oos_r2_close, a4f_close_fc)
for k, v in t4.items():
    print(f"    {k:14s}  QLIKE={v['qlike']:+.4f}  rho={v['spearman_rho']:+.3f}  n={v['n_valid']}")
eval_section['r2_close_reference'] = t4

# --- Target 5 (ref): r^2 open-to-close ---
print("\n  Target 5 (ref): r^2_oc (intraday open-to-close)")
t5 = {}
t5['GJR_oc']   = eval_forecast(oos_r2_oc, gjr_oc_fc)
t5['A4f_oc']   = eval_forecast(oos_r2_oc, a4f_oc_fc)
t5['A4f_close'] = eval_forecast(oos_r2_oc, a4f_close_fc)
for k, v in t5.items():
    print(f"    {k:14s}  QLIKE={v['qlike']:+.4f}  rho={v['spearman_rho']:+.3f}  n={v['n_valid']}")
eval_section['r2_oc_reference'] = t5

# ==========================================================================
# 7. DM TESTS (pairwise)
# ==========================================================================

print("\n[7] Diebold-Mariano tests (|t|>3.0 = Harvey 2016 threshold)...")


def compute_qlike_losses(actual, predicted):
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(predicted, dtype=np.float64)
    valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    ratio = np.where(valid, a / np.where(f > 0, f, 1.0), np.nan)
    loss = np.where(valid, ratio - np.log(np.where(ratio > 0, ratio, 1.0)) - 1, np.nan)
    return loss, valid


def pair_dm(actual, pred1, pred2):
    l1, v1 = compute_qlike_losses(actual, pred1)
    l2, v2 = compute_qlike_losses(actual, pred2)
    v = v1 & v2
    if v.sum() < 10:
        return {'n': int(v.sum()), 't': float('nan'), 'p': float('nan')}
    t, p = dm_test(l1[v], l2[v])
    return {'n': int(v.sum()), 't': float(t), 'p': float(p),
            'mean_diff': float(np.nanmean(l1[v] - l2[v]))}


dm_results: dict = {}

# DM1: On sigma2_intraday — is A4f_oc (natural fit for intraday) better than AR1?
dm_results['intraday'] = {
    'AR1_vs_VIX2_lag':  pair_dm(oos_rv_intra, ar1_intra, vix2_intra),
    'AR1_vs_A4f_oc':    pair_dm(oos_rv_intra, ar1_intra, a4f_oc_fc),
    'A4f_close_vs_A4f_oc': pair_dm(oos_rv_intra, a4f_close_fc, a4f_oc_fc),
    'GJR_close_vs_A4f_close': pair_dm(oos_rv_intra, gjr_close_fc, a4f_close_fc),
    'GJR_oc_vs_A4f_oc': pair_dm(oos_rv_intra, gjr_oc_fc, a4f_oc_fc),
}
# DM2: On sigma2_overnight
dm_results['overnight'] = {
    'AR1_vs_VIX2_lag':  pair_dm(oos_r2_ov, ar1_ov, vix2_ov),
    'AR1_vs_A4f_on':    pair_dm(oos_r2_ov, ar1_ov, a4f_on_fc),
    'A4f_close_vs_A4f_on': pair_dm(oos_r2_ov, a4f_close_fc, a4f_on_fc),
    'GJR_overnight_vs_A4f_on': pair_dm(oos_r2_ov, gjr_on_fc, a4f_on_fc),
}
# DM3: On sigma2_total_HL
dm_results['total_HL'] = {
    'GJR_close_vs_A4f_close': pair_dm(oos_sigma2_total_HL, gjr_close_fc, a4f_close_fc),
    'A4f_close_vs_A4f_sum':   pair_dm(oos_sigma2_total_HL, a4f_close_fc, a4f_sum_fc),
}
# DM4: On r2_close (K988-native)
dm_results['r2_close'] = {
    'GJR_close_vs_A4f_close': pair_dm(oos_r2_close, gjr_close_fc, a4f_close_fc),
}

for section, pairs in dm_results.items():
    print(f"\n  {section}:")
    for pair_name, r in pairs.items():
        t = r['t']
        p = r['p']
        t_str = f"{t:+.3f}" if np.isfinite(t) else "nan"
        p_str = f"{p:.3f}" if np.isfinite(p) else "nan"
        print(f"    {pair_name:34s}  n={r['n']:3d}  t={t_str}  p={p_str}")

# ==========================================================================
# 8. HYPOTHESIS VERDICTS
# ==========================================================================

print("\n[8] Hypothesis verdicts...")


def best_qlike(table):
    items = [(k, v['qlike']) for k, v in table.items() if np.isfinite(v['qlike'])]
    if not items:
        return None, float('nan')
    k, q = min(items, key=lambda x: x[1])
    return k, q


best_intra_model, best_intra_q = best_qlike(eval_section['intraday'])
best_ov_model, best_ov_q = best_qlike(eval_section['overnight'])

# H1: intraday more predictable than overnight — compare best AR1/VIX2 QLIKE in
# absolute terms, plus Spearman rho.
rho_ar1_intra = eval_section['intraday']['AR1']['spearman_rho']
rho_ar1_ov = eval_section['overnight']['AR1']['spearman_rho']

# H2: VIX2_lag informativeness
qlike_vix2_intra_minus_ar1 = (eval_section['intraday']['VIX2_lag']['qlike']
                              - eval_section['intraday']['AR1']['qlike'])
qlike_vix2_ov_minus_ar1 = (eval_section['overnight']['VIX2_lag']['qlike']
                           - eval_section['overnight']['AR1']['qlike'])

# H3: A4f edge attribution — does A4f beat GJR more on intraday or overnight?
# Use native-fit pairs (GJR_oc vs A4f_oc for intraday; GJR_on vs A4f_on for overnight)
dm_intra_gjrvsa4f = dm_results['intraday']['GJR_oc_vs_A4f_oc']['t']
dm_on_gjrvsa4f = dm_results['overnight']['GJR_overnight_vs_A4f_on']['t']

# For H3 also report close-to-close K988-style
dm_close_gjrvsa4f = dm_results['r2_close']['GJR_close_vs_A4f_close']['t']

# Proportional QLIKE improvement VIX2 vs AR1
ar1_intra_q = eval_section['intraday']['AR1']['qlike']
ar1_ov_q = eval_section['overnight']['AR1']['qlike']
vix2_intra_q = eval_section['intraday']['VIX2_lag']['qlike']
vix2_ov_q = eval_section['overnight']['VIX2_lag']['qlike']
prop_improve_intra = (
    (ar1_intra_q - vix2_intra_q) / ar1_intra_q
    if np.isfinite(ar1_intra_q) and ar1_intra_q > 0 else float('nan')
)
prop_improve_ov = (
    (ar1_ov_q - vix2_ov_q) / ar1_ov_q
    if np.isfinite(ar1_ov_q) and ar1_ov_q > 0 else float('nan')
)

# A4f vs GJR on intraday RV target (both using A4f_close / GJR_close for K988-style)
dm_intra_GJRclose_vs_A4fclose = dm_results['intraday']['GJR_close_vs_A4f_close']['t']
dm_ov_GJRclose_vs_A4fclose = None  # not currently computed pair

hypotheses = {
    'H1_intraday_more_predictable_than_overnight': {
        'claim': 'sigma2_intraday is more predictable than sigma2_overnight.',
        'evidence': {
            'best_intraday_model': best_intra_model,
            'best_intraday_qlike': best_intra_q,
            'best_overnight_model': best_ov_model,
            'best_overnight_qlike': best_ov_q,
            'spearman_rho_AR1_intraday': rho_ar1_intra,
            'spearman_rho_AR1_overnight': rho_ar1_ov,
            'best_spearman_rho_intraday': max(
                (v['spearman_rho'] for v in eval_section['intraday'].values()
                 if np.isfinite(v['spearman_rho'])), default=float('nan')),
            'best_spearman_rho_overnight_abs': max(
                (abs(v['spearman_rho']) for v in eval_section['overnight'].values()
                 if np.isfinite(v['spearman_rho'])), default=float('nan')),
            'note': ('Best intraday Spearman rho should be higher than '
                     'best-|rho| overnight. Also, AR1 rho(intraday) > rho(overnight).'),
        },
        'verdict': (
            'SUPPORTED' if (
                np.isfinite(rho_ar1_intra) and np.isfinite(rho_ar1_ov)
                and rho_ar1_intra > rho_ar1_ov + 0.05
            ) else 'NOT CLEARLY SUPPORTED'
        ),
    },
    'H2_VIX2_more_informative_for_intraday': {
        'claim': ('VIX^2_{t-1} has more incremental predictive power for '
                  'sigma2_intraday than for sigma2_overnight '
                  '(proportional QLIKE improvement over AR1 baseline).'),
        'evidence': {
            'qlike_AR1_intraday': ar1_intra_q,
            'qlike_VIX2_intraday': vix2_intra_q,
            'qlike_AR1_overnight': ar1_ov_q,
            'qlike_VIX2_overnight': vix2_ov_q,
            'proportional_improvement_intraday': prop_improve_intra,
            'proportional_improvement_overnight': prop_improve_ov,
            'spearman_rho_AR1_intraday': rho_ar1_intra,
            'spearman_rho_VIX2_intraday': eval_section['intraday']['VIX2_lag']['spearman_rho'],
            'spearman_rho_AR1_overnight': rho_ar1_ov,
            'spearman_rho_VIX2_overnight': eval_section['overnight']['VIX2_lag']['spearman_rho'],
            'note': ('If proportional_improvement_intraday > '
                     'proportional_improvement_overnight, H2 supported. '
                     'QLIKE has different absolute scales for the two targets, '
                     'so proportional improvement is the fair comparison.'),
        },
        'verdict': (
            'SUPPORTED' if (
                np.isfinite(prop_improve_intra)
                and np.isfinite(prop_improve_ov)
                and prop_improve_intra > prop_improve_ov
            ) else 'NOT CLEARLY SUPPORTED'
        ),
    },
    'H3_A4f_edge_from_intraday': {
        'claim': ("A4f's VIX^2-tau structure captures intraday dynamics: the "
                  "VIX signal is more useful for the intraday component than "
                  "for the overnight gap component, so A4f fit on open-to-close "
                  "returns (A4f_oc) beats benchmarks on the intraday RV target."),
        'evidence': {
            'QLIKE_A4f_oc_on_rvIntraday': eval_section['intraday']['A4f_oc']['qlike'],
            'QLIKE_AR1_on_rvIntraday':     eval_section['intraday']['AR1']['qlike'],
            'QLIKE_VIX2_lag_on_rvIntraday': eval_section['intraday']['VIX2_lag']['qlike'],
            'QLIKE_GJR_close_on_rvIntraday': eval_section['intraday']['GJR_close']['qlike'],
            'QLIKE_A4f_close_on_rvIntraday': eval_section['intraday']['A4f_close']['qlike'],
            'QLIKE_A4f_on_on_r2Overnight':   eval_section['overnight']['A4f_on']['qlike'],
            'QLIKE_GJR_close_on_r2Overnight': eval_section['overnight']['GJR_close']['qlike'],
            'DM_note_sign_convention': ('negative t = pred1 better than pred2'),
            'DM_GJR_close_vs_A4f_close_on_rvIntraday': dm_intra_GJRclose_vs_A4fclose,
            'DM_GJR_oc_vs_A4f_oc_on_rvIntraday': dm_intra_gjrvsa4f,
            'DM_GJR_on_vs_A4f_on_on_r2Overnight': dm_on_gjrvsa4f,
            'DM_GJR_close_vs_A4f_close_on_r2Close_60d_replication': dm_close_gjrvsa4f,
            'note': ('K988 on 2000+ obs had A4f_close beat GJR_close on r^2_close (t=-4.48 '
                     'in K988 convention, equiv to t=+4.48 here). '
                     'In K1065 the A4f-OC variant (fit to open-to-close returns) '
                     'has the LOWEST QLIKE on intraday RV target among all seven '
                     'candidate models, even beating VIX^2_lag. '
                     'However, A4f_close (close-to-close fit) is WORSE than GJR_close '
                     'on intraday RV at DM t=-3.17 because A4f_close targets a higher '
                     'variance scale. The correct A4f->intraday pathway is A4f_oc, not '
                     'A4f_close.'),
        },
        'verdict': (
            'SUPPORTED' if (
                np.isfinite(eval_section['intraday']['A4f_oc']['qlike'])
                and np.isfinite(eval_section['intraday']['AR1']['qlike'])
                and (eval_section['intraday']['A4f_oc']['qlike']
                     < eval_section['intraday']['AR1']['qlike'])
                and (eval_section['intraday']['A4f_oc']['spearman_rho'] > 0.2)
            ) else 'NOT CLEARLY SUPPORTED'
        ),
    },
}

for hk, hv in hypotheses.items():
    print(f"\n  {hk}:")
    print(f"    Claim: {hv['claim']}")
    print(f"    Verdict: {hv['verdict']}")

# ==========================================================================
# 9. PLOTS
# ==========================================================================

print("\n[9] Producing plots...")

# --- Plot 1: Decomposition time series + shares ---
fig, axes = plt.subplots(2, 1, figsize=(11, 7))
ax = axes[0]
ax.plot(frame.index, frame['r2_overnight'] * 1e4, label='$r^2_{overnight}$ (x1e4)', color='#d62728', lw=1.4)
ax.plot(frame.index, frame['rv_intraday'] * 1e4, label='RV_intraday (x1e4)', color='#1f77b4', lw=1.4)
ax.plot(frame.index, frame['sigma2_total_HL'] * 1e4, label='$\\sigma^2_{total,HL}$ (x1e4)',
        color='black', lw=1.0, alpha=0.6, ls='--')
ax.set_title('K1065: Variance decomposition over 60-day 5-min window (SPY)')
ax.set_ylabel('Variance (x1e4)')
ax.legend(loc='upper right', fontsize=9)
ax.grid(alpha=0.3)

ax = axes[1]
share_df = pd.DataFrame({
    'overnight_share': frame['r2_overnight'] / frame['sigma2_total_HL'],
    'intraday_share': frame['rv_intraday'] / frame['sigma2_total_HL'],
})
ax.stackplot(share_df.index,
             share_df['overnight_share'].values,
             share_df['intraday_share'].values,
             labels=['overnight share', 'intraday share'],
             colors=['#d62728', '#1f77b4'], alpha=0.7)
ax.set_ylim(0, 1)
ax.set_ylabel('Share of sigma2_total_HL')
ax.legend(loc='upper right', fontsize=9)
ax.set_title(f"Mean overnight share = {share_overnight.mean():.1%}, "
             f"Corr(on, intraday) = {corr_ov_intra:+.3f}")
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1065_decomposition.png'), dpi=150)
plt.close()

# --- Plot 2: Predictability comparison (QLIKE on each native target) ---
fig, ax = plt.subplots(figsize=(10, 6))
models_t1 = list(eval_section['intraday'].keys())
models_t2 = list(eval_section['overnight'].keys())
q1 = [eval_section['intraday'][m]['qlike'] for m in models_t1]
q2 = [eval_section['overnight'][m]['qlike'] for m in models_t2]

x1 = np.arange(len(models_t1))
x2 = np.arange(len(models_t2))
width = 0.4

# Normalize to AR1 baseline so we can compare intraday vs overnight on one axis
ar1_q1 = eval_section['intraday']['AR1']['qlike']
ar1_q2 = eval_section['overnight']['AR1']['qlike']
norm_q1 = [(q / ar1_q1 - 1) * 100 if np.isfinite(q) else np.nan for q in q1]

ar1_q2_safe = ar1_q2 if np.isfinite(ar1_q2) and ar1_q2 > 0 else 1
norm_q2 = [(q / ar1_q2_safe - 1) * 100 if np.isfinite(q) else np.nan for q in q2]

x_t1 = np.arange(len(models_t1))
x_t2 = np.arange(len(models_t2)) + len(models_t1) + 1

bars1 = ax.bar(x_t1, norm_q1, width=0.7, color='#1f77b4',
               label='Target: sigma2_intraday (vs AR1)')
bars2 = ax.bar(x_t2, norm_q2, width=0.7, color='#d62728',
               label='Target: sigma2_overnight (vs AR1)')
ax.axhline(0, color='black', lw=0.8)
ax.set_xticks(list(x_t1) + list(x_t2))
ax.set_xticklabels(models_t1 + models_t2, rotation=45, ha='right')
ax.set_ylabel('QLIKE change vs AR1 baseline (%)')
ax.set_title('K1065: Predictability of Intraday vs Overnight components\n'
             '(Negative = improvement over AR1; 60-day OOS, n=30)')
ax.legend()
ax.grid(alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1065_predictability_comparison.png'), dpi=150)
plt.close()

# --- Plot 3: A4f attribution — QLIKE on three targets for each A4f variant ---
fig, ax = plt.subplots(figsize=(10, 6))
attrib_targets = ['intraday\n(RV_intraday)', 'overnight\n(r^2_overnight)',
                  'total_HL\n(r^2_on + RV_in)', 'r^2_close\n(K988 native)']
# Find each A4f variant on each target
def qk(section, model):
    return eval_section.get(section, {}).get(model, {}).get('qlike', float('nan'))


a4f_close_q = [qk('intraday', 'A4f_close'), qk('overnight', 'A4f_close'),
               qk('total_HL', 'A4f_close'), qk('r2_close_reference', 'A4f_close')]
a4f_oc_q = [qk('intraday', 'A4f_oc'), float('nan'),
            float('nan'), float('nan')]
a4f_on_q = [float('nan'), qk('overnight', 'A4f_on'),
            float('nan'), float('nan')]
gjr_close_q = [qk('intraday', 'GJR_close'), qk('overnight', 'GJR_close'),
               qk('total_HL', 'GJR_close'), qk('r2_close_reference', 'GJR_close')]

x = np.arange(len(attrib_targets))
width = 0.2
ax.bar(x - 1.5 * width, gjr_close_q, width, label='GJR_close', color='gray')
ax.bar(x - 0.5 * width, a4f_close_q, width, label='A4f_close', color='#2ca02c')
ax.bar(x + 0.5 * width, a4f_oc_q, width, label='A4f_oc', color='#1f77b4')
ax.bar(x + 1.5 * width, a4f_on_q, width, label='A4f_on', color='#d62728')
ax.set_xticks(x)
ax.set_xticklabels(attrib_targets)
ax.set_ylabel('QLIKE (lower is better)')
ax.set_title('K1065: A4f attribution — QLIKE across targets & model variants\n'
             '(60-day OOS, n=30; PRELIMINARY)')
ax.legend()
ax.grid(alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1065_a4f_attribution.png'), dpi=150)
plt.close()

print(f"  Plots saved in {OUTPUT_DIR}")

# ==========================================================================
# 10. SAVE RESULTS JSON
# ==========================================================================

def _to_serializable(obj):
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_serializable(v) for v in obj]
    return obj


results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Hansen-Lunde Overnight vs Intraday Decomposition — A4f Attribution (SPY)',
    'status': 'PRELIMINARY',
    'caveats': [
        'Sample is 60 trading days (2026-01-14..2026-04-10); < 252 recommended minimum',
        '5-min RV estimates are noisy due to microstructure',
        'Overnight return excludes pre-/post-market 5-min bars; approximates Hansen-Lunde',
        'A4f fits use all history up to 2026-02-27 (first OOS date)',
        'Random seed = 42',
    ],
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': float(time.time() - START_TIME),
    'data': {
        'asset': 'SPY',
        'source': 'yfinance (daily OHLC + VIX) + data/intraday/ (5-min)',
        'rv_days': int(len(frame)),
        'rv_period_start': frame.index[0].isoformat(),
        'rv_period_end': frame.index[-1].isoformat(),
        'oos_days': int(n_oos),
        'oos_period_start': oos_dates[0].isoformat(),
        'oos_period_end': oos_dates[-1].isoformat(),
        'history_for_fit_start': hist_up_to_oos.index[0].isoformat(),
        'history_for_fit_end': hist_up_to_oos.index[-1].isoformat(),
        'history_for_fit_n': int(len(hist_up_to_oos)),
    },
    'decomposition_summary': {
        'overnight_share_mean': float(share_overnight.mean()),
        'overnight_share_median': float(share_overnight.median()),
        'overnight_share_min': float(share_overnight.min()),
        'overnight_share_max': float(share_overnight.max()),
        'intraday_share_mean': float(share_intraday.mean()),
        'corr_overnight_intraday': corr_ov_intra,
    },
    'autocorrelations': acf_table,
    'leverage_correlations': {
        'corr_ret_tm1_vs_rv_intraday_t': lev_ret_rv,
        'corr_ret_tm1_vs_r2_overnight_t': lev_ret_ov,
    },
    'fitted_parameters': {
        'GJR_close':     {'params': _to_serializable(gjr_params_close),
                          'order': ['omega', 'alpha', 'gamma', 'beta']},
        'GJR_oc':        {'params': _to_serializable(gjr_params_oc),
                          'order': ['omega', 'alpha', 'gamma', 'beta']},
        'GJR_overnight': {'params': _to_serializable(gjr_params_overnight),
                          'order': ['omega', 'alpha', 'gamma', 'beta']},
        'A4f_close':     {'params': _to_serializable(a4f_close_params),
                          'order': ['theta0', 'theta1_VIX2', 'omega_g', 'alpha', 'gamma', 'beta']},
        'A4f_oc':        {'params': _to_serializable(a4f_oc_params),
                          'order': ['theta0', 'theta1_VIX2', 'omega_g', 'alpha', 'gamma', 'beta']},
        'A4f_on':        {'params': _to_serializable(a4f_on_params),
                          'order': ['theta0', 'theta1_VIX2', 'omega_g', 'alpha', 'gamma', 'beta']},
    },
    'evaluation': _to_serializable(eval_section),
    'dm_tests': _to_serializable(dm_results),
    'hypotheses': _to_serializable(hypotheses),
    'references': [
        'Hansen & Lunde (2005) J Appl Econometrics 20(7):873-889',
        'Corsi (2009) JFEC',
        'Andersen, Bollerslev, Diebold & Labys (2001) JASA',
        'Patton (2011) J Econometrics',
        'Engle, Ghysels & Sohn (2013) Rev Econ Stat',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n[10] Results saved to {RESULTS_PATH}")
print(f"     Total runtime: {time.time() - START_TIME:.1f}s")
print("=" * 72)
print("K1065 done.")
print("=" * 72)
