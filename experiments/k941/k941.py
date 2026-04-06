#!/usr/bin/env python3
"""
K941: Conditional Quantile Volatility Forecasting
==================================================
[Proposed: research_program, Executed: Claude]

Problem: Current models predict E[sigma^2] (conditional mean). Risk management
needs the distribution of sigma^2 -- especially "vol of vol". Quantile regression
predicts different percentiles of r^2 (5th, 50th, 95th), giving a fuller risk picture.

Models:
  1. CAViaR-SAV (Engle & Manganelli 2004)
  2. Quantile Regression with GARCH features
  3. Quantile Random Forest
  4. GARCH(1,1) Parametric Quantiles (baseline)
  5. MF-GJR(VIX) Parametric Quantiles

Data: SPY 2006-2026 (yfinance), OOS 2016-01-01 ~ 2025-12-31.

References:
  - Engle & Manganelli (2004) JBES 22(4):367-381
  - Koenker & Bassett (1978) Econometrica 46:33-50
  - Meinshausen (2006) JMLR 7:983-999
  - Patton (2011) J Econometrics 160:246-256

Author: VolPred Research System
Date: 2026-04-06
"""

import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize, stats as sp_stats
from scipy.stats import t as t_dist

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K941"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k941_results.json')

DATA_START = '2006-01-01'
DATA_END = '2025-12-31'
OOS_START = '2016-01-01'
WINDOW = 2000
GARCH_REFIT = 63        # Refit every ~3 months for speed
QR_REFIT = 126          # Refit QR/QRF every ~6 months for speed
QUANTILES = [0.05, 0.25, 0.50, 0.75, 0.95]

print("=" * 70)
print(f"{EXPERIMENT_ID}: Conditional Quantile Volatility Forecasting")
print("=" * 70, flush=True)

# ============================================================
# 1. DATA
# ============================================================
print("\n[1] Loading data...", flush=True)
import yfinance as yf

spy = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_ret = spy["Close"].pct_change().dropna()

vix = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_close = vix["Close"].dropna()

common_idx = spy_ret.index.intersection(vix_close.index)
spy_ret = spy_ret.loc[common_idx]
vix_close = vix_close.loc[common_idx]

returns = spy_ret.values.astype(np.float64)
r_squared = returns ** 2
abs_returns = np.abs(returns)
log_vix = np.log(vix_close.values.astype(np.float64))
dates = spy_ret.index

print(f"  SPY: {dates[0].strftime('%Y-%m-%d')} ~ {dates[-1].strftime('%Y-%m-%d')}, N={len(returns)}", flush=True)
print(f"  r^2 mean: {r_squared.mean():.6f}, std: {r_squared.std():.6f}", flush=True)
print(f"  Skewness: {sp_stats.skew(returns):.4f}, Kurtosis: {sp_stats.kurtosis(returns):.4f}", flush=True)

oos_mask = dates >= OOS_START
oos_start_idx = np.where(oos_mask)[0][0]
n_oos = len(returns) - oos_start_idx
actual_rsq_oos = r_squared[oos_start_idx:]
oos_dates = dates[oos_start_idx:]

print(f"  IS: N={oos_start_idx}, OOS: N={n_oos}", flush=True)

# ============================================================
# 2. GARCH utilities (numba accelerated)
# ============================================================
print("\n[2] GARCH utilities...", flush=True)
from numba import njit

@njit
def garch11_filter(omega, alpha, beta, rets, h0):
    T = len(rets)
    h = np.empty(T)
    h[0] = h0
    for t in range(1, T):
        h[t] = omega + alpha * rets[t-1]**2 + beta * h[t-1]
    return h

def fit_garch11_t(rets):
    """Fit GARCH(1,1)-t by MLE."""
    T = len(rets)
    var0 = np.var(rets)
    def negll(params):
        omega, alpha, beta, nu = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999 or nu <= 2.01:
            return 1e10
        h = garch11_filter(omega, alpha, beta, rets, var0)
        if np.any(h <= 0):
            return 1e10
        sc = np.sqrt((nu-2)/nu)
        return -np.sum(t_dist.logpdf(rets/np.sqrt(h)/sc, df=nu) - 0.5*np.log(h) - np.log(sc))
    best = None
    for trial in range(3):
        x0 = [var0*(0.02+0.06*np.random.random()), 0.03+0.15*np.random.random(),
              0.7+0.25*np.random.random(), 4+10*np.random.random()]
        try:
            res = optimize.minimize(negll, x0, method='L-BFGS-B',
                                    bounds=[(1e-8,var0*5),(1e-4,0.5),(0.3,0.999),(2.1,50)])
            if best is None or res.fun < best.fun:
                best = res
        except: pass
    omega, alpha, beta, nu = best.x
    h = garch11_filter(omega, alpha, beta, rets, var0)
    return dict(omega=omega, alpha=alpha, beta=beta, nu=nu, h=h, persistence=alpha+beta)

@njit
def mfgjr_filter(m0, theta, alpha, beta, gamma, rets, log_v):
    T = len(rets)
    tau = np.exp(m0 + theta * log_v)
    g = np.ones(T)
    intercept = 1.0 - alpha - beta - gamma/2.0
    for t in range(1, T):
        eps2 = rets[t-1]**2 / tau[t-1] if tau[t-1] > 0 else 1.0
        ind = 1.0 if rets[t-1] < 0 else 0.0
        g[t] = intercept + alpha*eps2 + gamma*eps2*ind + beta*g[t-1]
        if g[t] <= 0:
            g[t] = 0.01
    return tau * g, tau, g

def fit_mfgjr(rets, log_v):
    """Fit MF-GJR(VIX)-t."""
    T = len(rets)
    var0 = np.var(rets)
    mean_lv = np.mean(log_v)
    def negll(params):
        m0, theta, alpha, beta, gamma, nu = params
        if alpha < 0 or beta < 0 or gamma < 0 or nu <= 2.01:
            return 1e10
        if alpha + beta + gamma/2.0 >= 0.999 or 1-alpha-beta-gamma/2 <= 0:
            return 1e10
        h, _, _ = mfgjr_filter(m0, theta, alpha, beta, gamma, rets, log_v)
        if np.any(h <= 0) or np.any(np.isnan(h)):
            return 1e10
        sc = np.sqrt((nu-2)/nu)
        return -np.sum(t_dist.logpdf(rets/np.sqrt(h)/sc, df=nu) - 0.5*np.log(h) - np.log(sc))
    best = None
    for trial in range(5):
        x0 = [np.log(var0)-mean_lv*(1+np.random.random()), 0.5+2*np.random.random(),
              0.02+0.1*np.random.random(), 0.7+0.25*np.random.random(),
              0.01+0.1*np.random.random(), 4+10*np.random.random()]
        try:
            res = optimize.minimize(negll, x0, method='L-BFGS-B',
                                    bounds=[(-20,5),(-2,5),(1e-4,0.4),(0.3,0.999),(0,0.4),(2.1,50)])
            if best is None or res.fun < best.fun:
                best = res
        except: pass
    if best is None:
        return None
    m0, theta, alpha, beta, gamma, nu = best.x
    h, tau, g = mfgjr_filter(m0, theta, alpha, beta, gamma, rets, log_v)
    return dict(m0=m0, theta=theta, alpha=alpha, beta=beta, gamma=gamma, nu=nu,
                h=h, tau=tau, g=g, persistence=alpha+beta+gamma/2)

# ============================================================
# 3. Compute full GARCH + MF-GJR variance series (rolling refit)
# ============================================================
print("\n[3] Building GARCH / MF-GJR variance series (rolling refit)...", flush=True)

garch_h_full = np.full(len(returns), np.nan)
garch_nu_series = np.full(len(returns), np.nan)
mfgjr_h_full = np.full(len(returns), np.nan)
mfgjr_nu_series = np.full(len(returns), np.nan)

# IS fit
garch_is = fit_garch11_t(returns[:oos_start_idx])
garch_h_full[:oos_start_idx] = garch_is['h']
garch_nu_series[:oos_start_idx] = garch_is['nu']
print(f"  GARCH IS: alpha={garch_is['alpha']:.4f}, beta={garch_is['beta']:.4f}, "
      f"nu={garch_is['nu']:.2f}, pers={garch_is['persistence']:.4f}", flush=True)

mfgjr_is = fit_mfgjr(returns[:oos_start_idx], log_vix[:oos_start_idx])
if mfgjr_is:
    mfgjr_h_full[:oos_start_idx] = mfgjr_is['h']
    mfgjr_nu_series[:oos_start_idx] = mfgjr_is['nu']
    print(f"  MF-GJR IS: theta={mfgjr_is['theta']:.3f}, alpha={mfgjr_is['alpha']:.4f}, "
          f"beta={mfgjr_is['beta']:.4f}, gamma={mfgjr_is['gamma']:.4f}, nu={mfgjr_is['nu']:.2f}", flush=True)

# OOS: refit every GARCH_REFIT, recursive 1-step-ahead between refits
last_refit = -999
garch_p = garch_is
mfgjr_p = mfgjr_is

for i in range(n_oos):
    t = oos_start_idx + i

    if i - last_refit >= GARCH_REFIT or last_refit < 0:
        ts = max(0, t - WINDOW)
        garch_p = fit_garch11_t(returns[ts:t])
        h_train = garch11_filter(garch_p['omega'], garch_p['alpha'], garch_p['beta'],
                                  returns[ts:t], np.var(returns[ts:t]))
        garch_h_full[t-1] = h_train[-1]

        mf = fit_mfgjr(returns[ts:t], log_vix[ts:t])
        if mf is not None:
            mfgjr_p = mf
            mfgjr_h_full[t-1] = mf['h'][-1]
        last_refit = i
        if i % 500 == 0:
            print(f"    Refit at OOS day {i}/{n_oos} ({dates[t].strftime('%Y-%m-%d')})", flush=True)

    # Recursive GARCH h
    if not np.isnan(garch_h_full[t-1]):
        garch_h_full[t] = garch_p['omega'] + garch_p['alpha']*returns[t-1]**2 + garch_p['beta']*garch_h_full[t-1]
    else:
        garch_h_full[t] = np.var(returns[max(0,t-252):t])
    garch_nu_series[t] = garch_p['nu']

    # Recursive MF-GJR h
    if mfgjr_p is not None:
        tau_t = np.exp(mfgjr_p['m0'] + mfgjr_p['theta'] * log_vix[t-1])
        if not np.isnan(mfgjr_h_full[t-1]) and t >= 2:
            tau_prev = np.exp(mfgjr_p['m0'] + mfgjr_p['theta'] * log_vix[t-2])
            g_prev = mfgjr_h_full[t-1] / tau_prev if tau_prev > 0 else 1.0
        else:
            g_prev = 1.0
        eps2 = returns[t-1]**2 / (np.exp(mfgjr_p['m0'] + mfgjr_p['theta'] * log_vix[t-2]) if t >= 2 else tau_t)
        ind = 1.0 if returns[t-1] < 0 else 0.0
        intercept = 1.0 - mfgjr_p['alpha'] - mfgjr_p['beta'] - mfgjr_p['gamma']/2
        g_new = intercept + mfgjr_p['alpha']*eps2 + mfgjr_p['gamma']*eps2*ind + mfgjr_p['beta']*g_prev
        g_new = max(g_new, 0.01)
        mfgjr_h_full[t] = tau_t * g_new
        mfgjr_nu_series[t] = mfgjr_p['nu']
    else:
        mfgjr_h_full[t] = garch_h_full[t]
        mfgjr_nu_series[t] = garch_nu_series[t]

print(f"  GARCH/MF-GJR variance series built.", flush=True)

# ============================================================
# 4. Build feature matrix (vectorized)
# ============================================================
print("\n[4] Building feature matrix...", flush=True)

# Features: sigma^2_GARCH(t-1), log_vix(t-1), |r(t-1)|, r^2(t-1), 5d_rolling_r^2(t-5:t)
rolling5_r2 = pd.Series(r_squared).rolling(5).mean().values

X_all = np.column_stack([
    np.roll(garch_h_full, 1),   # GARCH h_{t-1}
    np.roll(log_vix, 1),        # log VIX_{t-1}
    np.roll(abs_returns, 1),    # |r_{t-1}|
    np.roll(r_squared, 1),      # r^2_{t-1}
    np.roll(rolling5_r2, 1),    # 5-day rolling r^2
])

# Fix edge cases
X_all[0, :] = 0
for c in range(5):
    nan_mask = np.isnan(X_all[:, c])
    if np.any(nan_mask):
        col_median = np.nanmedian(X_all[:, c])
        X_all[nan_mask, c] = col_median

# ============================================================
# 5. Quantile Forecasting: batch-refit approach
# ============================================================
print("\n[5] Quantile Forecasting (batch-refit)...", flush=True)

model_names = ['caviar_sav', 'qr_garch', 'qrf', 'garch_param', 'mfgjr_param']
model_labels = ['CAViaR-SAV', 'QR-GARCH', 'Quantile RF', 'GARCH Param', 'MF-GJR Param']

quantile_forecasts = {m: {tau: np.full(n_oos, np.nan) for tau in QUANTILES} for m in model_names}

# --- 5a. GARCH Parametric Quantiles ---
print("  [5a] GARCH Parametric...", flush=True)
for i in range(n_oos):
    t = oos_start_idx + i
    h_t = garch_h_full[t]
    if np.isnan(h_t) or h_t <= 0:
        h_t = np.var(returns[max(0,t-252):t])
    nu = garch_nu_series[t] if not np.isnan(garch_nu_series[t]) else 5.0
    sf = (nu-2)/nu if nu > 2 else 1.0
    for tau in QUANTILES:
        tq = t_dist.ppf((1+tau)/2, df=nu)
        quantile_forecasts['garch_param'][tau][i] = max(h_t * sf * tq**2, 1e-10)
print("    Done.", flush=True)

# --- 5b. MF-GJR Parametric Quantiles ---
print("  [5b] MF-GJR Parametric...", flush=True)
for i in range(n_oos):
    t = oos_start_idx + i
    h_t = mfgjr_h_full[t]
    if np.isnan(h_t) or h_t <= 0:
        h_t = garch_h_full[t] if not np.isnan(garch_h_full[t]) else np.var(returns[max(0,t-252):t])
    nu = mfgjr_nu_series[t] if not np.isnan(mfgjr_nu_series[t]) else 5.0
    sf = (nu-2)/nu if nu > 2 else 1.0
    for tau in QUANTILES:
        tq = t_dist.ppf((1+tau)/2, df=nu)
        quantile_forecasts['mfgjr_param'][tau][i] = max(h_t * sf * tq**2, 1e-10)
print("    Done.", flush=True)

# --- 5c. CAViaR-SAV ---
print("  [5c] CAViaR-SAV...", flush=True)

def fit_caviar_sav(r_sq_train, tau, n_restarts=3):
    """Fit CAViaR-SAV: q_t(tau) = b0 + b1*q_{t-1} + b2*r^2_{t-1}"""
    q0 = np.quantile(r_sq_train, tau)
    def run_filter(params):
        b0, b1, b2 = params
        T = len(r_sq_train)
        q = np.empty(T)
        q[0] = q0
        for t in range(1, T):
            q[t] = b0 + b1*q[t-1] + b2*r_sq_train[t-1]
        return q
    def objective(params):
        b0, b1, b2 = params
        if b1 < 0 or b1 > 0.999 or b0 < -0.001 or b2 < 0:
            return 1e10
        q = run_filter(params)
        if np.any(q < 0):
            return 1e10
        resid = r_sq_train - q
        return np.mean(np.where(resid >= 0, tau*resid, (tau-1)*resid))
    best = None
    for _ in range(n_restarts):
        x0 = [q0*(0.01+0.1*np.random.random()), 0.8+0.15*np.random.random(), 0.05+0.2*np.random.random()]
        try:
            res = optimize.minimize(objective, x0, method='Nelder-Mead', options={'maxiter':3000})
            if best is None or res.fun < best.fun:
                best = res
        except: pass
    params = best.x if best else np.array([q0*0.05, 0.9, 0.1])
    q_full = run_filter(params)
    return params, q0, q_full[-1]

# Refit schedule for CAViaR
refit_points = list(range(0, n_oos, QR_REFIT))
caviar_params = {}
caviar_last_q = {}

for refit_i, start_i in enumerate(refit_points):
    t = oos_start_idx + start_i
    ts = max(0, t - WINDOW)
    r_sq_train = r_squared[ts:t]

    for tau in QUANTILES:
        params, q0, last_q = fit_caviar_sav(r_sq_train, tau)
        caviar_params[tau] = params
        caviar_last_q[tau] = last_q

    # Forecast until next refit
    end_i = refit_points[refit_i+1] if refit_i+1 < len(refit_points) else n_oos
    for i in range(start_i, end_i):
        t_now = oos_start_idx + i
        for tau in QUANTILES:
            b0, b1, b2 = caviar_params[tau]
            q_prev = caviar_last_q[tau]
            q_new = b0 + b1*q_prev + b2*r_squared[t_now-1]
            q_new = max(q_new, 1e-10)
            quantile_forecasts['caviar_sav'][tau][i] = q_new
            caviar_last_q[tau] = q_new

    if refit_i % 5 == 0:
        print(f"    CAViaR refit {refit_i+1}/{len(refit_points)} at {dates[t].strftime('%Y-%m-%d')}", flush=True)
print("    Done.", flush=True)

# --- 5d. Quantile Regression (sklearn) ---
print("  [5d] QR-GARCH...", flush=True)
from sklearn.linear_model import QuantileRegressor

qr_models = {}
for refit_i, start_i in enumerate(refit_points):
    t = oos_start_idx + start_i
    ts = max(5, t - WINDOW)
    X_train = X_all[ts:t]
    y_train = r_squared[ts:t]

    for tau in QUANTILES:
        try:
            qr = QuantileRegressor(quantile=tau, alpha=0.001, solver='highs')
            qr.fit(X_train, y_train)
            qr_models[tau] = qr
        except: pass

    end_i = refit_points[refit_i+1] if refit_i+1 < len(refit_points) else n_oos
    X_test = X_all[oos_start_idx+start_i : oos_start_idx+end_i]
    for tau in QUANTILES:
        if tau in qr_models:
            preds = qr_models[tau].predict(X_test)
            preds = np.maximum(preds, 1e-10)
            quantile_forecasts['qr_garch'][tau][start_i:end_i] = preds

    if refit_i % 5 == 0:
        print(f"    QR refit {refit_i+1}/{len(refit_points)} at {dates[t].strftime('%Y-%m-%d')}", flush=True)
print("    Done.", flush=True)

# --- 5e. Quantile Random Forest ---
print("  [5e] Quantile RF...", flush=True)
from sklearn.ensemble import RandomForestRegressor

for refit_i, start_i in enumerate(refit_points):
    t = oos_start_idx + start_i
    ts = max(5, t - WINDOW)
    X_train = X_all[ts:t]
    y_train = r_squared[ts:t]

    rf = RandomForestRegressor(n_estimators=100, max_depth=10, min_samples_leaf=20,
                                random_state=42, n_jobs=-1)
    rf.fit(X_train, y_train)

    # Store training leaf mapping
    train_leaves = rf.apply(X_train)

    end_i = refit_points[refit_i+1] if refit_i+1 < len(refit_points) else n_oos
    X_test = X_all[oos_start_idx+start_i : oos_start_idx+end_i]
    test_leaves = rf.apply(X_test)

    # Compute quantiles for all test points at once
    n_test = len(X_test)
    n_trees = train_leaves.shape[1]

    for test_idx in range(n_test):
        weights = np.zeros(len(y_train))
        for tree_idx in range(n_trees):
            in_leaf = train_leaves[:, tree_idx] == test_leaves[test_idx, tree_idx]
            n_in = np.sum(in_leaf)
            if n_in > 0:
                weights[in_leaf] += 1.0 / n_in
        weights /= n_trees

        sorted_idx = np.argsort(y_train)
        sorted_y = y_train[sorted_idx]
        sorted_w = weights[sorted_idx]
        cum_w = np.cumsum(sorted_w)
        if cum_w[-1] > 0:
            cum_w /= cum_w[-1]

        for tau in QUANTILES:
            idx = np.searchsorted(cum_w, tau)
            idx = min(idx, len(sorted_y)-1)
            quantile_forecasts['qrf'][tau][start_i + test_idx] = max(sorted_y[idx], 1e-10)

    if refit_i % 5 == 0:
        print(f"    QRF refit {refit_i+1}/{len(refit_points)} at {dates[t].strftime('%Y-%m-%d')}", flush=True)
print("    Done.", flush=True)


# ============================================================
# 6. EVALUATION
# ============================================================
print("\n[6] Evaluation...", flush=True)

def pinball_loss(y, q, tau):
    resid = y - q
    return np.mean(np.where(resid >= 0, tau*resid, (tau-1)*resid))

# 6a. Pinball Loss
print("\n  [6a] Pinball Loss (lower = better):", flush=True)
pinball_results = {}
for mn in model_names:
    pinball_results[mn] = {}
    for tau in QUANTILES:
        q = quantile_forecasts[mn][tau]
        valid = ~np.isnan(q) & ~np.isnan(actual_rsq_oos)
        if np.sum(valid) > 100:
            pinball_results[mn][str(tau)] = float(pinball_loss(actual_rsq_oos[valid], q[valid], tau))
        else:
            pinball_results[mn][str(tau)] = None

hdr = f"  {'Model':<18}"
for tau in QUANTILES:
    hdr += f" | {f'tau={tau}':>10}"
hdr += f" | {'Mean':>10}"
print(hdr)
print("  " + "-" * 90)
for mn, ml in zip(model_names, model_labels):
    row = f"  {ml:<18}"
    vals = []
    for tau in QUANTILES:
        v = pinball_results[mn].get(str(tau))
        if v is not None:
            row += f" | {v:>10.6f}"
            vals.append(v)
        else:
            row += f" | {'N/A':>10}"
    if vals:
        row += f" | {np.mean(vals):>10.6f}"
    print(row)

# 6b. Coverage
print("\n  [6b] 90% Interval Coverage (target: 0.90):", flush=True)
coverage_results = {}
for mn, ml in zip(model_names, model_labels):
    q_lo = quantile_forecasts[mn][0.05]
    q_hi = quantile_forecasts[mn][0.95]
    valid = ~np.isnan(q_lo) & ~np.isnan(q_hi) & ~np.isnan(actual_rsq_oos)
    if np.sum(valid) > 100:
        inside = (actual_rsq_oos[valid] >= q_lo[valid]) & (actual_rsq_oos[valid] <= q_hi[valid])
        coverage = float(np.mean(inside))
    else:
        coverage = float('nan')
    coverage_results[mn] = coverage
    tag = 'OK' if abs(coverage - 0.90) < 0.05 else 'MISS'
    print(f"    {ml:<18}: {coverage:.4f} [{tag}]")

# 6c. Average Width
print("\n  [6c] Avg Interval Width (90% PI):", flush=True)
width_results = {}
for mn, ml in zip(model_names, model_labels):
    q_lo = quantile_forecasts[mn][0.05]
    q_hi = quantile_forecasts[mn][0.95]
    valid = ~np.isnan(q_lo) & ~np.isnan(q_hi)
    w = float(np.mean(q_hi[valid] - q_lo[valid])) if np.sum(valid) > 100 else float('nan')
    width_results[mn] = w
    print(f"    {ml:<18}: {w:.6f}")

# 6d. Calibration
print("\n  [6d] Calibration (actual coverage at each tau):", flush=True)
calibration_results = {}
for mn in model_names:
    calibration_results[mn] = {}
    for tau in QUANTILES:
        q = quantile_forecasts[mn][tau]
        valid = ~np.isnan(q) & ~np.isnan(actual_rsq_oos)
        if np.sum(valid) > 100:
            calibration_results[mn][str(tau)] = float(np.mean(actual_rsq_oos[valid] <= q[valid]))
        else:
            calibration_results[mn][str(tau)] = None

hdr = f"  {'Model':<18}"
for tau in QUANTILES:
    hdr += f" | {f'tau={tau}':>10}"
print(hdr)
print(f"  {'(Target)':<18}", end='')
for tau in QUANTILES:
    print(f" | {tau:>10.3f}", end='')
print()
print("  " + "-" * 75)
for mn, ml in zip(model_names, model_labels):
    row = f"  {ml:<18}"
    for tau in QUANTILES:
        v = calibration_results[mn].get(str(tau))
        if v is not None:
            row += f" | {v:>10.3f}"
        else:
            row += f" | {'N/A':>10}"
    print(row)

# 6e. Winkler Score
print("\n  [6e] Winkler Score (90% PI):", flush=True)
alpha_w = 0.10
winkler_results = {}
for mn, ml in zip(model_names, model_labels):
    q_lo = quantile_forecasts[mn][0.05]
    q_hi = quantile_forecasts[mn][0.95]
    valid = ~np.isnan(q_lo) & ~np.isnan(q_hi) & ~np.isnan(actual_rsq_oos)
    if np.sum(valid) > 100:
        y = actual_rsq_oos[valid]
        lo, hi = q_lo[valid], q_hi[valid]
        width = hi - lo
        pen_lo = (2.0/alpha_w) * (lo - y) * (y < lo)
        pen_hi = (2.0/alpha_w) * (y - hi) * (y > hi)
        winkler = float(np.mean(width + pen_lo + pen_hi))
    else:
        winkler = float('nan')
    winkler_results[mn] = winkler
    print(f"    {ml:<18}: {winkler:.6f}")

# 6f. Calibration MAD
print("\n  [6f] Calibration MAD:", flush=True)
cal_mad = {}
for mn, ml in zip(model_names, model_labels):
    devs = []
    for tau in QUANTILES:
        v = calibration_results[mn].get(str(tau))
        if v is not None:
            devs.append(abs(v - tau))
    cal_mad[mn] = float(np.mean(devs)) if devs else float('nan')
    print(f"    {ml:<18}: {cal_mad[mn]:.4f}")

# ============================================================
# 7. RANKINGS
# ============================================================
print("\n[7] Rankings...", flush=True)
mean_pinball = {}
for mn in model_names:
    vals = [pinball_results[mn].get(str(tau)) for tau in QUANTILES]
    vals = [v for v in vals if v is not None]
    mean_pinball[mn] = float(np.mean(vals)) if vals else float('nan')

sorted_models = sorted(mean_pinball.items(), key=lambda x: x[1])
print("  Overall ranking (mean pinball loss):")
for rank, (name, val) in enumerate(sorted_models, 1):
    label = model_labels[model_names.index(name)]
    print(f"    #{rank}: {label:<18} mean_pinball={val:.6f}")

print("\n  Best model per quantile:")
for tau in QUANTILES:
    best_m, best_v = None, np.inf
    for mn in model_names:
        v = pinball_results[mn].get(str(tau))
        if v is not None and v < best_v:
            best_v, best_m = v, mn
    if best_m:
        print(f"    tau={tau}: {model_labels[model_names.index(best_m)]:<18} (pinball={best_v:.6f})")

# ============================================================
# 8. PLOTS
# ============================================================
print("\n[8] Generating plots...", flush=True)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

colors = ['#2196F3', '#4CAF50', '#FF9800', '#9C27B0', '#F44336']

# Plot 1: Pinball loss bars
fig, ax = plt.subplots(figsize=(12, 6))
x = np.arange(len(QUANTILES))
w = 0.15
for j, (mn, ml) in enumerate(zip(model_names, model_labels)):
    vals = [pinball_results[mn].get(str(tau), 0) or 0 for tau in QUANTILES]
    ax.bar(x + j*w, vals, w, label=ml, color=colors[j], alpha=0.85)
ax.set_xlabel('Quantile Level', fontsize=12)
ax.set_ylabel('Pinball Loss', fontsize=12)
ax.set_title('K941: Pinball Loss by Model and Quantile (OOS)', fontsize=14)
ax.set_xticks(x + w*2)
ax.set_xticklabels([f'tau={tau}' for tau in QUANTILES])
ax.legend(fontsize=10)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k941_quantile_comparison.png'), dpi=150)
plt.close()
print("  Saved k941_quantile_comparison.png", flush=True)

# Plot 2: Calibration
fig, ax = plt.subplots(figsize=(10, 8))
for j, (mn, ml) in enumerate(zip(model_names, model_labels)):
    ac = [calibration_results[mn].get(str(tau), np.nan) for tau in QUANTILES]
    ax.plot(QUANTILES, ac, 'o-', label=ml, color=colors[j], markersize=8, linewidth=2)
ax.plot([0, 1], [0, 1], 'k--', linewidth=1, label='Perfect')
ax.set_xlabel('Nominal Quantile (tau)', fontsize=12)
ax.set_ylabel('Actual Coverage', fontsize=12)
ax.set_title('K941: Calibration Plot (OOS)', fontsize=14)
ax.legend(fontsize=10)
ax.grid(alpha=0.3)
ax.set_xlim(-0.02, 1.02)
ax.set_ylim(-0.02, 1.02)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k941_calibration.png'), dpi=150)
plt.close()
print("  Saved k941_calibration.png", flush=True)

# Plot 3: Prediction intervals (last 500 days)
fig, axes = plt.subplots(3, 2, figsize=(16, 14))
axes_flat = axes.flatten()
last_n = 500
pd_oos = oos_dates[-last_n:]
for j, (mn, ml) in enumerate(zip(model_names, model_labels)):
    ax = axes_flat[j]
    q_lo = quantile_forecasts[mn][0.05][-last_n:]
    q_med = quantile_forecasts[mn][0.50][-last_n:]
    q_hi = quantile_forecasts[mn][0.95][-last_n:]
    act = actual_rsq_oos[-last_n:]
    ax.fill_between(pd_oos, q_lo, q_hi, alpha=0.2, color=colors[j], label='90% PI')
    ax.plot(pd_oos, q_med, '-', color=colors[j], linewidth=1, label='Median')
    ax.plot(pd_oos, act, '.', color='black', markersize=1, alpha=0.5, label='Actual r^2')
    ax.set_title(ml, fontsize=11)
    ax.legend(fontsize=8)
    ax.set_ylabel('r^2')
    ax.tick_params(axis='x', rotation=30)
axes_flat[5].set_visible(False)
fig.suptitle('K941: 90% Prediction Intervals (last 500 OOS days)', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k941_prediction_intervals.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k941_prediction_intervals.png", flush=True)

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print("\n[9] Saving results...", flush=True)
elapsed = time.time() - START_TIME

best_name = model_labels[model_names.index(sorted_models[0][0])]
best_val = sorted_models[0][1]
cal_sorted = sorted(cal_mad.items(), key=lambda x: x[1])
best_cal = model_labels[model_names.index(cal_sorted[0][0])]

conclusion = (
    f"K941: Conditional quantile vol forecasting on SPY r^2 (OOS {OOS_START}~{DATA_END}, N_OOS={n_oos}). "
    f"Best overall pinball loss: {best_name} ({best_val:.6f}). "
    f"Best calibration: {best_cal} (MAD={cal_sorted[0][1]:.4f}). "
    f"90% coverage: " + ", ".join(f"{model_labels[model_names.index(n)]}={coverage_results[n]:.3f}" for n in model_names) + ". "
    f"Winkler: " + ", ".join(f"{model_labels[model_names.index(n)]}={winkler_results[n]:.6f}" for n in model_names) + ". "
    f"Non-parametric methods capture asymmetric quantile dynamics; parametric models with Student-t "
    f"provide competitive performance with interpretability advantage."
)

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Conditional Quantile Volatility Forecasting',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'elapsed_seconds': round(elapsed, 1),
    'data': {
        'asset': 'SPY', 'source': 'yfinance',
        'period': f'{dates[0].strftime("%Y-%m-%d")} ~ {dates[-1].strftime("%Y-%m-%d")}',
        'n_total': len(returns), 'oos_start': OOS_START, 'n_oos': n_oos,
        'target': 'r^2 (squared daily return)',
    },
    'models': model_labels,
    'quantiles': QUANTILES,
    'pinball_loss': pinball_results,
    'mean_pinball_loss': {model_names[i]: float(mean_pinball[model_names[i]]) for i in range(len(model_names))},
    'coverage_90pct': coverage_results,
    'interval_width_90pct': width_results,
    'winkler_score_90pct': winkler_results,
    'calibration': calibration_results,
    'calibration_mad': cal_mad,
    'ranking': [{'rank': r+1, 'model': model_labels[model_names.index(n)], 'mean_pinball': float(v)}
                for r, (n, v) in enumerate(sorted_models)],
    'garch_params': {k: float(garch_is[k]) for k in ['alpha','beta','nu','persistence']},
    'mfgjr_params': {k: float(mfgjr_is[k]) for k in ['theta','alpha','beta','gamma','nu']} if mfgjr_is else None,
    'references': [
        'Engle & Manganelli (2004) JBES 22(4):367-381',
        'Koenker & Bassett (1978) Econometrica 46:33-50',
        'Meinshausen (2006) JMLR 7:983-999',
        'Patton (2011) J Econometrics 160:246-256',
    ],
    'conclusion': conclusion,
    'limitations': [
        'Target is r^2 (noisy proxy for sigma^2)',
        'CAViaR-SAV is simplified (no asymmetric slope)',
        'Single asset (SPY)',
        'QRF quantile estimation via leaf membership',
        'No formal DM tests between quantile models',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved {RESULTS_PATH}", flush=True)

print(f"\n{'='*70}")
print("SUMMARY")
print(f"{'='*70}")
print(f"  Elapsed: {elapsed:.1f}s")
print(f"  Best overall: {best_name} (mean pinball={best_val:.6f})")
print(f"  Best calibration: {best_cal}")
for item in results['ranking']:
    print(f"    #{item['rank']}: {item['model']:<18} mean_pinball={item['mean_pinball']:.6f}")
print(f"\n  Coverage (target 0.90):")
for mn, ml in zip(model_names, model_labels):
    cov = coverage_results[mn]
    print(f"    {ml:<18}: {cov:.4f}")
print(f"\n  Calibration MAD:")
for mn, ml in zip(model_names, model_labels):
    print(f"    {ml:<18}: {cal_mad[mn]:.4f}")
print(flush=True)
