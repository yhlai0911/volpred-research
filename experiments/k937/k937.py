"""
K937: CARR-GARCH Rank-Calibration Ensemble
Can ensemble methods combine CARR's superior ranking with GARCH's superior calibration?

Background:
  K934: CARR(1,1) Spearman rho=0.474 (best ranking) but QLIKE=1.815 (worst calibration)
  K935: Yang-Zhang CARR beats Parkinson by 8%, QLIKE=1.556, close to GARCH(1.603)
  K482: MCS-Weighted Ensemble -- equal weight beats MCS (combination puzzle confirmed)
  K475/K476: Simple Ensemble -- equal weight best
  K889: MF-GJR(VIX) QLIKE=~1.47 (best known)

Hypotheses:
  H1: Rank-level hybrid (CARR ranking + GARCH levels) beats both individual models
  H2: Inverse-QLIKE weighting beats equal weight
  H3: No ensemble beats MF-GJR(VIX) alone (VIX already sufficient)

Models (base):
  1. GARCH(1,1)
  2. GJR(1,1,1)
  3. MF-GJR(VIX) -- best known single model
  4. CARR_YZ(1,1) -- Yang-Zhang CARR

Ensemble methods:
  1. Equal Weight
  2. Inverse QLIKE Weight (rolling 252-day)
  3. Rank-Level Hybrid (CARR ranking + GARCH percentile mapping)
  4. OLS Stacking (rolling 252-day)

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - Spearman rank correlation
  - DM test (Harvey |t| > 3.0)

References:
  Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies"
  Timmermann (2006) "Forecast Combinations" in Handbook of Economic Forecasting
  Yang & Zhang (2000) "Drift Independent Volatility Estimation"
  Engle & Manganelli (2004) "CAViaR"
  Harvey et al. (2016) "Tests for Forecast Encompassing"

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2004-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000, Refit: every 21 trading days
Seed: 42

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy.optimize import minimize
from scipy import stats

np.random.seed(42)
warnings.filterwarnings('ignore')

# Add project root for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K937: CARR-GARCH Rank-Calibration Ensemble")
print("=" * 60)

print("\n[1/8] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-01-01', progress=False)

# Flatten multi-level columns if needed
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Log prices
spy['log_H'] = np.log(spy['High'])
spy['log_L'] = np.log(spy['Low'])
spy['log_O'] = np.log(spy['Open'])
spy['log_C'] = np.log(spy['Close'])

# Returns
spy['log_return'] = spy['log_C'] - spy['log_C'].shift(1)
spy['r2'] = spy['log_return'] ** 2

# Overnight return
spy['overnight_return'] = spy['log_O'] - spy['log_C'].shift(1)

# Yang-Zhang range estimator (from K935)
spy['overnight_sq'] = spy['overnight_return'] ** 2
spy['range_rs'] = ((spy['log_H'] - spy['log_C']) * (spy['log_H'] - spy['log_O'])
                  + (spy['log_L'] - spy['log_C']) * (spy['log_L'] - spy['log_O']))
k_yz = 0.34 / (1.34 + 2.0)  # asymptotic k
spy['open_var'] = ((spy['log_H'] - spy['log_O'])**2 + (spy['log_L'] - spy['log_O'])**2)
spy['range_yz'] = spy['overnight_sq'] + k_yz * spy['open_var'] + (1 - k_yz) * spy['range_rs']

# Add VIX
vix_close = vix['Close'].rename('VIX')
spy = spy.join(vix_close, how='left')
spy['VIX'] = spy['VIX'].ffill()
spy['log_VIX'] = np.log(spy['VIX'])

# Drop NaN
spy = spy.dropna(subset=['range_yz', 'log_return', 'r2', 'VIX', 'overnight_return'])

# Floor range at small positive value
FLOOR = 1e-10
spy['range_yz'] = np.maximum(spy['range_yz'], FLOOR)

print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Descriptive stats
print("\n  Descriptive Statistics:")
for name, col in [('YZ Range', 'range_yz'), ('r2', 'r2'), ('VIX', 'VIX')]:
    vals = spy[col]
    print(f"    {name:12s}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
          f"skew={vals.skew():.3f}, kurt={vals.kurtosis():.3f}")


# ============================================================
# 2. MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2/8] Model implementations...")


def garch_fit(returns, max_iter=500):
    """GARCH(1,1) MLE with Normal innovations."""
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    mean_r2 = np.mean(r**2)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2*np.pi) + np.log(h) + r**2 / h)
        return -np.sum(ll[10:])

    x0 = [mean_r2 * 0.05, 0.08, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.92), (0.12, 0.85), (0.03, 0.95)]:
            x0_alt = [mean_r2 * 0.05, a0, b0]
            r_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': max_iter, 'ftol': 1e-12})
            if r_alt.success and r_alt.fun < result.fun:
                result = r_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success}


def garch_forecast_oos(params, returns):
    """Recursive one-step-ahead GARCH forecast."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        h[t+1] = omega + alpha * r[t]**2 + beta * h[t]
        if h[t+1] <= 1e-10:
            h[t+1] = 1e-10
    return h[1:]


def gjr_fit(returns, max_iter=500):
    """GJR-GARCH(1,1,1) MLE."""
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    mean_r2 = np.mean(r**2)

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5*gamma + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - 0.5*gamma - beta) if (alpha + 0.5*gamma + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * (r[t-1] < 0) + beta * h[t-1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2*np.pi) + np.log(h) + r**2 / h)
        return -np.sum(ll[10:])

    x0 = [mean_r2 * 0.05, 0.02, 0.10, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.0, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, g0, b0 in [(0.01, 0.15, 0.85), (0.03, 0.08, 0.88), (0.05, 0.12, 0.80)]:
            x0_alt = [mean_r2 * 0.05, a0, g0, b0]
            r_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': max_iter, 'ftol': 1e-12})
            if r_alt.success and r_alt.fun < result.fun:
                result = r_alt

    omega, alpha, gamma, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5*gamma + beta, 'converged': result.success}


def gjr_forecast_oos(params, returns):
    """Recursive one-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - 0.5*gamma - beta, 0.01)
    for t in range(T):
        h[t+1] = omega + alpha * r[t]**2 + gamma * r[t]**2 * (r[t] < 0) + beta * h[t]
        if h[t+1] <= 1e-10:
            h[t+1] = 1e-10
    return h[1:]


def mf_gjr_fit(returns, log_vix, max_iter=500):
    """MF-GJR(VIX) -- Multiplicative Factor GJR with VIX as long-run component."""
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    lv = np.asarray(log_vix, dtype=np.float64)
    mean_r2 = np.mean(r**2)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5*gamma + beta) >= 0.9999:
            return 1e10

        tau = np.exp(theta0 + theta1 * lv)
        tau = np.maximum(tau, 1e-16)

        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            shock = r[t-1]**2 / tau[t-1]
            asym = shock * (r[t-1] < 0)
            g[t] = omega + alpha * shock + gamma * asym + beta * g[t-1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        h = tau * g
        ll = -0.5 * (np.log(2*np.pi) + np.log(h) + r**2 / h)
        return -np.sum(ll[10:])

    omega0 = 0.02
    x0 = [np.log(mean_r2) - 0.5 * np.mean(lv), 0.5, omega0, 0.02, 0.10, 0.85]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (0.0, 0.5), (0.0, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.3, 0.7, 1.0]:
            x0_alt = [x0[0], t1, 0.05, 0.02, 0.10, 0.85]
            r_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': max_iter, 'ftol': 1e-12})
            if r_alt.success and r_alt.fun < result.fun:
                result = r_alt

    theta0, theta1, omega, alpha, gamma, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5*gamma + beta, 'converged': result.success}


def mf_gjr_forecast_oos(params, returns, log_vix):
    """Recursive one-step-ahead MF-GJR forecast."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    lv = np.asarray(log_vix, dtype=np.float64)

    tau = np.exp(theta0 + theta1 * lv)
    tau = np.maximum(tau, 1e-16)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        shock = r[t]**2 / tau[t]
        asym = shock * (r[t] < 0)
        g[t+1] = omega + alpha * shock + gamma * asym + beta * g[t]
        if g[t+1] <= 1e-10:
            g[t+1] = 1e-10

    # For forecast at t+1, we use tau[t] (last known VIX) since VIX at t+1 unknown
    # But in rolling OOS, we actually have VIX up to t, so we use tau values directly
    h = tau * g[1:]
    return h


def carr_yz_fit(ranges, max_iter=500):
    """CARR(1,1) with Exponential innovation on Yang-Zhang range."""
    T = len(ranges)
    rng = np.asarray(ranges, dtype=np.float64)
    mean_r = np.mean(rng)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(T)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for t in range(1, T):
            lam[t] = omega + alpha * rng[t-1] + beta * lam[t-1]
            if lam[t] <= 1e-10:
                lam[t] = 1e-10
        ll = -np.log(lam) - rng / lam
        return -np.sum(ll[10:])

    omega0 = mean_r * 0.05
    x0 = [omega0, 0.10, 0.85]
    bounds = [(1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.90), (0.15, 0.80), (0.08, 0.88)]:
            x0_alt = [mean_r * 0.05, a0, b0]
            r_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': max_iter, 'ftol': 1e-12})
            if r_alt.success and r_alt.fun < result.fun:
                result = r_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success}


def carr_yz_forecast_oos(params, ranges):
    """Recursive one-step-ahead CARR_YZ forecast (predicts E[YZ range])."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(ranges)
    rng = np.asarray(ranges, dtype=np.float64)
    lam = np.zeros(T + 1)
    lam[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        lam[t+1] = omega + alpha * rng[t] + beta * lam[t]
        if lam[t+1] <= 1e-10:
            lam[t+1] = 1e-10
    return lam[1:]


# ============================================================
# 3. ROLLING OOS ESTIMATION
# ============================================================
print("\n[3/8] Rolling OOS estimation...")

WINDOW = 2000
REFIT_EVERY = 21
OOS_START = '2016-01-01'

# Find OOS start index
oos_mask = spy.index >= OOS_START
oos_start_idx = spy.index.get_loc(spy.index[oos_mask][0])
print(f"  Window: {WINDOW}, Refit every: {REFIT_EVERY}")
print(f"  OOS start: {spy.index[oos_mask][0].strftime('%Y-%m-%d')} (idx={oos_start_idx})")
print(f"  OOS days: {oos_mask.sum()}")

returns_arr = spy['log_return'].values
r2_arr = spy['r2'].values
range_yz_arr = spy['range_yz'].values
log_vix_arr = spy['log_VIX'].values

n_total = len(spy)
n_oos = oos_mask.sum()

# Storage for OOS forecasts
fc_garch = np.full(n_total, np.nan)
fc_gjr = np.full(n_total, np.nan)
fc_mfgjr = np.full(n_total, np.nan)
fc_carr_yz = np.full(n_total, np.nan)  # This is E[YZ range], NOT sigma^2

# Rolling estimation
params_garch = None
params_gjr = None
params_mfgjr = None
params_carr_yz = None

refit_counter = 0
n_refits = 0

for t in range(oos_start_idx, n_total):
    # Refit if needed
    if params_garch is None or refit_counter >= REFIT_EVERY:
        train_start = max(0, t - WINDOW)
        train_ret = returns_arr[train_start:t]
        train_range = range_yz_arr[train_start:t]
        train_lvix = log_vix_arr[train_start:t]

        params_garch = garch_fit(train_ret)
        params_gjr = gjr_fit(train_ret)
        params_mfgjr = mf_gjr_fit(train_ret, train_lvix)
        params_carr_yz = carr_yz_fit(train_range)

        refit_counter = 0
        n_refits += 1

        if n_refits <= 3 or n_refits % 20 == 0:
            print(f"    Refit #{n_refits} at t={t} ({spy.index[t].strftime('%Y-%m-%d')})"
                  f" GARCH pers={params_garch['persistence']:.4f}"
                  f" GJR pers={params_gjr['persistence']:.4f}"
                  f" MF-GJR pers={params_mfgjr['persistence']:.4f}"
                  f" CARR_YZ pers={params_carr_yz['persistence']:.4f}")

    refit_counter += 1

    # Recursive OOS forecasts using all data up to t-1
    # For GARCH/GJR/MF-GJR: h[t] = f(h[t-1], r^2[t-1])
    # We need to build the full conditional variance path from training start
    train_start = max(0, t - WINDOW)

    # GARCH
    h_garch = garch_forecast_oos(params_garch, returns_arr[train_start:t])
    fc_garch[t] = h_garch[-1]  # Forecast for time t using info up to t-1

    # GJR
    h_gjr = gjr_forecast_oos(params_gjr, returns_arr[train_start:t])
    fc_gjr[t] = h_gjr[-1]

    # MF-GJR(VIX)
    h_mfgjr = mf_gjr_forecast_oos(params_mfgjr, returns_arr[train_start:t], log_vix_arr[train_start:t])
    fc_mfgjr[t] = h_mfgjr[-1]

    # CARR_YZ: produces E[YZ range] -- we keep as-is for ranking, convert to sigma^2 for QLIKE
    lam_carr = carr_yz_forecast_oos(params_carr_yz, range_yz_arr[train_start:t])
    fc_carr_yz[t] = lam_carr[-1]

print(f"\n  Total refits: {n_refits}")

# ============================================================
# 4. CARR-TO-SIGMA^2 CONVERSION
# ============================================================
print("\n[4/8] CARR-to-sigma^2 conversion...")

# CARR_YZ predicts E[YZ_range]. YZ range is already a variance estimator (unbiased for sigma^2).
# So CARR_YZ forecast = E[sigma^2_YZ] which is directly comparable to sigma^2.
# No further conversion needed -- YZ is designed to estimate daily variance including overnight.
# This is a key advantage of YZ over Parkinson (K935 confirmed).

# Extract OOS arrays
oos_idx = spy.index[oos_mask]
r2_oos = r2_arr[oos_mask]
fc_garch_oos = fc_garch[oos_mask]
fc_gjr_oos = fc_gjr[oos_mask]
fc_mfgjr_oos = fc_mfgjr[oos_mask]
fc_carr_yz_oos = fc_carr_yz[oos_mask]

# Validate no NaN
for name, fc in [('GARCH', fc_garch_oos), ('GJR', fc_gjr_oos),
                 ('MF-GJR', fc_mfgjr_oos), ('CARR_YZ', fc_carr_yz_oos)]:
    n_nan = np.isnan(fc).sum()
    if n_nan > 0:
        print(f"  WARNING: {name} has {n_nan} NaN forecasts")
    else:
        print(f"  {name}: {len(fc)} OOS forecasts, no NaN")

# ============================================================
# 5. ENSEMBLE METHODS
# ============================================================
print("\n[5/8] Computing ensemble forecasts...")

# Method 1: Equal Weight
fc_equal = (fc_garch_oos + fc_gjr_oos + fc_mfgjr_oos + fc_carr_yz_oos) / 4.0
print(f"  Equal Weight: mean={fc_equal.mean():.8f}")

# Method 2: Inverse QLIKE Weight (rolling 252-day)
ROLLING_W = 252
fc_inv_qlike = np.full(len(r2_oos), np.nan)
rolling_weights_inv = []

for t in range(ROLLING_W, len(r2_oos)):
    # Compute QLIKE for each model over past 252 days
    window_r2 = r2_oos[t-ROLLING_W:t]
    q_garch = qlike(window_r2, fc_garch_oos[t-ROLLING_W:t])
    q_gjr = qlike(window_r2, fc_gjr_oos[t-ROLLING_W:t])
    q_mfgjr = qlike(window_r2, fc_mfgjr_oos[t-ROLLING_W:t])
    q_carr = qlike(window_r2, fc_carr_yz_oos[t-ROLLING_W:t])

    # Inverse QLIKE weights (lower QLIKE = higher weight)
    inv_q = np.array([1.0/q_garch, 1.0/q_gjr, 1.0/q_mfgjr, 1.0/q_carr])
    weights = inv_q / inv_q.sum()

    fc_inv_qlike[t] = (weights[0] * fc_garch_oos[t] + weights[1] * fc_gjr_oos[t]
                       + weights[2] * fc_mfgjr_oos[t] + weights[3] * fc_carr_yz_oos[t])
    rolling_weights_inv.append(weights)

rolling_weights_inv = np.array(rolling_weights_inv)
print(f"  Inverse QLIKE Weight: {np.sum(~np.isnan(fc_inv_qlike))} valid forecasts")
print(f"    Mean weights: GARCH={rolling_weights_inv[:,0].mean():.3f}, "
      f"GJR={rolling_weights_inv[:,1].mean():.3f}, "
      f"MF-GJR={rolling_weights_inv[:,2].mean():.3f}, "
      f"CARR_YZ={rolling_weights_inv[:,3].mean():.3f}")

# Method 3: Rank-Level Hybrid (CARR ranking + GARCH percentiles)
# Idea: CARR has superior ranking ability (Spearman rho=0.474 in K934)
# but poor calibration. GARCH has good calibration.
# Use CARR to rank, then map to GARCH forecast distribution.
fc_rank_hybrid = np.full(len(r2_oos), np.nan)

for t in range(ROLLING_W, len(r2_oos)):
    # Get CARR forecasts in rolling window and compute their rank percentiles
    carr_window = fc_carr_yz_oos[t-ROLLING_W:t+1]
    carr_current = fc_carr_yz_oos[t]
    # Rank percentile of current CARR forecast among recent history
    rank_pct = np.mean(carr_window[:-1] <= carr_current)  # percentile

    # Get GARCH forecasts in rolling window
    garch_window = fc_garch_oos[t-ROLLING_W:t]
    # Map to the corresponding percentile in GARCH distribution
    fc_rank_hybrid[t] = np.percentile(garch_window, rank_pct * 100)

print(f"  Rank-Level Hybrid: {np.sum(~np.isnan(fc_rank_hybrid))} valid forecasts")

# Method 4: OLS Stacking (rolling 252-day)
fc_ols_stack = np.full(len(r2_oos), np.nan)
rolling_weights_ols = []

for t in range(ROLLING_W, len(r2_oos)):
    # OLS: r^2 = a1*fc_garch + a2*fc_gjr + a3*fc_mfgjr + a4*fc_carr + epsilon
    # No intercept (constrained to go through origin for positivity)
    y = r2_oos[t-ROLLING_W:t]
    X = np.column_stack([
        fc_garch_oos[t-ROLLING_W:t],
        fc_gjr_oos[t-ROLLING_W:t],
        fc_mfgjr_oos[t-ROLLING_W:t],
        fc_carr_yz_oos[t-ROLLING_W:t]
    ])

    # OLS with non-negative constraint (to ensure positive forecasts)
    from scipy.optimize import nnls
    weights_ols, _ = nnls(X, y)

    # Normalize weights to sum to 1
    w_sum = weights_ols.sum()
    if w_sum > 0:
        weights_ols = weights_ols / w_sum
    else:
        weights_ols = np.array([0.25, 0.25, 0.25, 0.25])

    fc_ols_stack[t] = (weights_ols[0] * fc_garch_oos[t] + weights_ols[1] * fc_gjr_oos[t]
                       + weights_ols[2] * fc_mfgjr_oos[t] + weights_ols[3] * fc_carr_yz_oos[t])
    rolling_weights_ols.append(weights_ols)

rolling_weights_ols = np.array(rolling_weights_ols)
print(f"  OLS Stacking: {np.sum(~np.isnan(fc_ols_stack))} valid forecasts")
print(f"    Mean weights: GARCH={rolling_weights_ols[:,0].mean():.3f}, "
      f"GJR={rolling_weights_ols[:,1].mean():.3f}, "
      f"MF-GJR={rolling_weights_ols[:,2].mean():.3f}, "
      f"CARR_YZ={rolling_weights_ols[:,3].mean():.3f}")

# ============================================================
# 6. EVALUATION
# ============================================================
print("\n[6/8] Evaluation...")

# Use common valid period (after ROLLING_W warm-up)
valid_mask = ~np.isnan(fc_inv_qlike)
r2_valid = r2_oos[valid_mask]
n_valid = len(r2_valid)
print(f"  Valid evaluation period: {n_valid} days")
print(f"  Date range: {oos_idx[valid_mask][0].strftime('%Y-%m-%d')} ~ "
      f"{oos_idx[valid_mask][-1].strftime('%Y-%m-%d')}")

forecasts = {
    'GARCH': fc_garch_oos[valid_mask],
    'GJR': fc_gjr_oos[valid_mask],
    'MF-GJR(VIX)': fc_mfgjr_oos[valid_mask],
    'CARR_YZ': fc_carr_yz_oos[valid_mask],
    'EQ Weight': fc_equal[valid_mask],
    'Inv QLIKE': fc_inv_qlike[valid_mask],
    'Rank Hybrid': fc_rank_hybrid[valid_mask],
    'OLS Stack': fc_ols_stack[valid_mask],
}

# 6a. QLIKE on r^2
print("\n  --- QLIKE on r^2 (lower = better) ---")
qlike_results = {}
for name, fc in forecasts.items():
    q = qlike(r2_valid, fc)
    qlike_results[name] = q
    print(f"    {name:15s}: QLIKE = {q:.4f}")

# 6b. Spearman rank correlation
print("\n  --- Spearman Rank Correlation with r^2 (higher = better) ---")
spearman_results = {}
for name, fc in forecasts.items():
    rho, pval = stats.spearmanr(r2_valid, fc)
    spearman_results[name] = {'rho': rho, 'pval': pval}
    print(f"    {name:15s}: rho = {rho:.4f} (p={pval:.2e})")

# 6c. MSE
print("\n  --- MSE (lower = better) ---")
mse_results = {}
for name, fc in forecasts.items():
    mse = np.mean((r2_valid - fc)**2)
    mse_results[name] = mse
    print(f"    {name:15s}: MSE = {mse:.4e}")

# 6d. DM tests (Harvey threshold |t| > 3.0)
print("\n  --- DM Tests (vs MF-GJR(VIX)) ---")
print("    H0: Equal predictive ability | Harvey |t| > 3.0 threshold")
dm_results = {}
loss_mfgjr = qlike_pointwise(r2_valid, forecasts['MF-GJR(VIX)'])

for name, fc in forecasts.items():
    if name == 'MF-GJR(VIX)':
        continue
    loss_other = qlike_pointwise(r2_valid, fc)
    t_stat, p_val = dm_test(loss_mfgjr, loss_other, h=1)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.645 else ""))
    # Negative t_stat means MF-GJR is better (lower loss)
    direction = "MF-GJR better" if t_stat < 0 else f"{name} better"
    dm_results[name] = {'t_stat': t_stat, 'p_val': p_val, 'direction': direction}
    print(f"    vs {name:15s}: t={t_stat:+.3f} p={p_val:.4f} {sig} ({direction})")

# 6e. DM tests between ensemble methods
print("\n  --- DM Tests (Ensemble vs Ensemble) ---")
ensemble_names = ['EQ Weight', 'Inv QLIKE', 'Rank Hybrid', 'OLS Stack']
dm_ensemble = {}
for i, name1 in enumerate(ensemble_names):
    for j, name2 in enumerate(ensemble_names):
        if i >= j:
            continue
        loss1 = qlike_pointwise(r2_valid, forecasts[name1])
        loss2 = qlike_pointwise(r2_valid, forecasts[name2])
        t_stat, p_val = dm_test(loss1, loss2, h=1)
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
        better = name1 if t_stat < 0 else name2
        dm_ensemble[f"{name1} vs {name2}"] = {'t_stat': t_stat, 'p_val': p_val, 'better': better}
        print(f"    {name1:12s} vs {name2:12s}: t={t_stat:+.3f} p={p_val:.4f} {sig} (better: {better})")

# 6f. Best model identification
print("\n  --- Summary ---")
best_qlike = min(qlike_results, key=qlike_results.get)
best_spearman = max(spearman_results, key=lambda k: spearman_results[k]['rho'])
print(f"  Best QLIKE:    {best_qlike} ({qlike_results[best_qlike]:.4f})")
print(f"  Best Spearman: {best_spearman} ({spearman_results[best_spearman]['rho']:.4f})")

# Check if any ensemble beats MF-GJR significantly
any_beats_mfgjr = False
for name in ensemble_names:
    if name in dm_results and dm_results[name]['t_stat'] > 3.0:
        any_beats_mfgjr = True
        print(f"  ** {name} SIGNIFICANTLY beats MF-GJR(VIX) (t={dm_results[name]['t_stat']:.3f}) **")

if not any_beats_mfgjr:
    print("  No ensemble significantly beats MF-GJR(VIX) at Harvey t>3.0 threshold")

# ============================================================
# 7. VISUALIZATION
# ============================================================
print("\n[7/8] Creating plots...")

fig, axes = plt.subplots(2, 2, figsize=(16, 12))
fig.suptitle('K937: CARR-GARCH Rank-Calibration Ensemble', fontsize=14, fontweight='bold')

# Panel A: QLIKE comparison
ax = axes[0, 0]
names = list(qlike_results.keys())
values = [qlike_results[n] for n in names]
colors = ['#1f77b4', '#1f77b4', '#ff7f0e', '#2ca02c',  # base models
          '#d62728', '#9467bd', '#8c564b', '#e377c2']  # ensembles
bars = ax.barh(range(len(names)), values, color=colors)
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names)
ax.set_xlabel('QLIKE on r^2 (lower = better)')
ax.set_title('(A) QLIKE Comparison')
ax.axvline(x=qlike_results['MF-GJR(VIX)'], color='red', linestyle='--', alpha=0.5, label='MF-GJR(VIX)')
ax.legend(fontsize=8)
# Add value labels
for bar, val in zip(bars, values):
    ax.text(val + 0.005, bar.get_y() + bar.get_height()/2, f'{val:.3f}',
            va='center', fontsize=9)

# Panel B: Spearman comparison
ax = axes[0, 1]
rho_values = [spearman_results[n]['rho'] for n in names]
bars = ax.barh(range(len(names)), rho_values, color=colors)
ax.set_yticks(range(len(names)))
ax.set_yticklabels(names)
ax.set_xlabel('Spearman rho with r^2 (higher = better)')
ax.set_title('(B) Spearman Rank Correlation')
ax.axvline(x=spearman_results['MF-GJR(VIX)']['rho'], color='red', linestyle='--', alpha=0.5)
for bar, val in zip(bars, rho_values):
    ax.text(val + 0.003, bar.get_y() + bar.get_height()/2, f'{val:.3f}',
            va='center', fontsize=9)

# Panel C: Rolling weights (Inv QLIKE)
ax = axes[1, 0]
valid_dates = oos_idx[valid_mask]
w_dates = valid_dates[:len(rolling_weights_inv)]
# Align dates with rolling weights
offset_start = ROLLING_W
w_dates_aligned = oos_idx[offset_start:offset_start + len(rolling_weights_inv)]
ax.fill_between(w_dates_aligned, 0, rolling_weights_inv[:, 0], alpha=0.7, label='GARCH')
ax.fill_between(w_dates_aligned, rolling_weights_inv[:, 0],
                rolling_weights_inv[:, 0] + rolling_weights_inv[:, 1], alpha=0.7, label='GJR')
ax.fill_between(w_dates_aligned, rolling_weights_inv[:, 0] + rolling_weights_inv[:, 1],
                rolling_weights_inv[:, 0] + rolling_weights_inv[:, 1] + rolling_weights_inv[:, 2],
                alpha=0.7, label='MF-GJR')
ax.fill_between(w_dates_aligned,
                rolling_weights_inv[:, 0] + rolling_weights_inv[:, 1] + rolling_weights_inv[:, 2],
                1.0, alpha=0.7, label='CARR_YZ')
ax.set_ylabel('Weight')
ax.set_title('(C) Inverse QLIKE Rolling Weights')
ax.legend(fontsize=8, loc='upper right')
ax.set_ylim(0, 1)

# Panel D: OLS Stacking weights
ax = axes[1, 1]
w_dates_ols = oos_idx[offset_start:offset_start + len(rolling_weights_ols)]
ax.fill_between(w_dates_ols, 0, rolling_weights_ols[:, 0], alpha=0.7, label='GARCH')
ax.fill_between(w_dates_ols, rolling_weights_ols[:, 0],
                rolling_weights_ols[:, 0] + rolling_weights_ols[:, 1], alpha=0.7, label='GJR')
ax.fill_between(w_dates_ols, rolling_weights_ols[:, 0] + rolling_weights_ols[:, 1],
                rolling_weights_ols[:, 0] + rolling_weights_ols[:, 1] + rolling_weights_ols[:, 2],
                alpha=0.7, label='MF-GJR')
ax.fill_between(w_dates_ols,
                rolling_weights_ols[:, 0] + rolling_weights_ols[:, 1] + rolling_weights_ols[:, 2],
                1.0, alpha=0.7, label='CARR_YZ')
ax.set_ylabel('Weight')
ax.set_title('(D) OLS Stacking Rolling Weights')
ax.legend(fontsize=8, loc='upper right')
ax.set_ylim(0, 1)

plt.tight_layout()
chart_path = os.path.join(SCRIPT_DIR, 'k937_ensemble_comparison.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart_path}")

# ============================================================
# 8. SAVE RESULTS
# ============================================================
print("\n[8/8] Saving results...")

results = {
    'experiment_id': 'K937',
    'title': 'CARR-GARCH Rank-Calibration Ensemble',
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance (SPY + ^VIX)',
    'period': '2004-01-01 ~ 2025-12-31',
    'oos_period': f"{oos_idx[valid_mask][0].strftime('%Y-%m-%d')} ~ {oos_idx[valid_mask][-1].strftime('%Y-%m-%d')}",
    'oos_days': int(n_valid),
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': n_refits,
    'seed': 42,
    'base_models': {
        'GARCH': {
            'qlike': float(qlike_results['GARCH']),
            'spearman_rho': float(spearman_results['GARCH']['rho']),
            'mse': float(mse_results['GARCH']),
        },
        'GJR': {
            'qlike': float(qlike_results['GJR']),
            'spearman_rho': float(spearman_results['GJR']['rho']),
            'mse': float(mse_results['GJR']),
        },
        'MF-GJR(VIX)': {
            'qlike': float(qlike_results['MF-GJR(VIX)']),
            'spearman_rho': float(spearman_results['MF-GJR(VIX)']['rho']),
            'mse': float(mse_results['MF-GJR(VIX)']),
        },
        'CARR_YZ': {
            'qlike': float(qlike_results['CARR_YZ']),
            'spearman_rho': float(spearman_results['CARR_YZ']['rho']),
            'mse': float(mse_results['CARR_YZ']),
        },
    },
    'ensemble_methods': {
        'EQ_Weight': {
            'qlike': float(qlike_results['EQ Weight']),
            'spearman_rho': float(spearman_results['EQ Weight']['rho']),
            'mse': float(mse_results['EQ Weight']),
            'dm_vs_mfgjr': {
                't_stat': float(dm_results['EQ Weight']['t_stat']),
                'p_val': float(dm_results['EQ Weight']['p_val']),
                'direction': dm_results['EQ Weight']['direction'],
            }
        },
        'Inv_QLIKE': {
            'qlike': float(qlike_results['Inv QLIKE']),
            'spearman_rho': float(spearman_results['Inv QLIKE']['rho']),
            'mse': float(mse_results['Inv QLIKE']),
            'mean_weights': {
                'GARCH': float(rolling_weights_inv[:, 0].mean()),
                'GJR': float(rolling_weights_inv[:, 1].mean()),
                'MF-GJR': float(rolling_weights_inv[:, 2].mean()),
                'CARR_YZ': float(rolling_weights_inv[:, 3].mean()),
            },
            'dm_vs_mfgjr': {
                't_stat': float(dm_results['Inv QLIKE']['t_stat']),
                'p_val': float(dm_results['Inv QLIKE']['p_val']),
                'direction': dm_results['Inv QLIKE']['direction'],
            }
        },
        'Rank_Hybrid': {
            'qlike': float(qlike_results['Rank Hybrid']),
            'spearman_rho': float(spearman_results['Rank Hybrid']['rho']),
            'mse': float(mse_results['Rank Hybrid']),
            'dm_vs_mfgjr': {
                't_stat': float(dm_results['Rank Hybrid']['t_stat']),
                'p_val': float(dm_results['Rank Hybrid']['p_val']),
                'direction': dm_results['Rank Hybrid']['direction'],
            }
        },
        'OLS_Stack': {
            'qlike': float(qlike_results['OLS Stack']),
            'spearman_rho': float(spearman_results['OLS Stack']['rho']),
            'mse': float(mse_results['OLS Stack']),
            'mean_weights': {
                'GARCH': float(rolling_weights_ols[:, 0].mean()),
                'GJR': float(rolling_weights_ols[:, 1].mean()),
                'MF-GJR': float(rolling_weights_ols[:, 2].mean()),
                'CARR_YZ': float(rolling_weights_ols[:, 3].mean()),
            },
            'dm_vs_mfgjr': {
                't_stat': float(dm_results['OLS Stack']['t_stat']),
                'p_val': float(dm_results['OLS Stack']['p_val']),
                'direction': dm_results['OLS Stack']['direction'],
            }
        },
    },
    'dm_tests_ensemble_vs_ensemble': {},
    'best_qlike_model': best_qlike,
    'best_spearman_model': best_spearman,
    'any_ensemble_beats_mfgjr_sig': any_beats_mfgjr,
    'conclusions': [],
    'references': [
        'Chou (2005) Forecasting Financial Volatilities with Extreme Values, JoE',
        'Patton (2011) Volatility Forecast Comparison Using Imperfect Volatility Proxies, JoE 160',
        'Timmermann (2006) Forecast Combinations, Handbook of Economic Forecasting',
        'Yang & Zhang (2000) Drift Independent Volatility Estimation, JoF 55(3)',
        'Harvey et al. (2016) Tests for Forecast Encompassing, JBES',
    ],
}

# Add ensemble DM tests
for key, val in dm_ensemble.items():
    results['dm_tests_ensemble_vs_ensemble'][key] = {
        't_stat': float(val['t_stat']),
        'p_val': float(val['p_val']),
        'better': val['better'],
    }

# Generate conclusions
conclusions = []

# C1: Does any ensemble beat MF-GJR?
if any_beats_mfgjr:
    beating = [n for n in ensemble_names if n in dm_results and dm_results[n]['t_stat'] > 3.0]
    conclusions.append(f"Ensemble(s) {', '.join(beating)} significantly beat MF-GJR(VIX) at Harvey t>3.0")
else:
    conclusions.append("No ensemble significantly beats MF-GJR(VIX) at Harvey t>3.0 -- VIX information is sufficient")

# C2: Best ensemble vs equal weight
eq_qlike = qlike_results['EQ Weight']
best_ens_name = min(ensemble_names, key=lambda n: qlike_results[n])
best_ens_qlike = qlike_results[best_ens_name]
if best_ens_qlike < eq_qlike:
    conclusions.append(f"Best ensemble {best_ens_name} (QLIKE={best_ens_qlike:.4f}) beats Equal Weight ({eq_qlike:.4f})")
else:
    conclusions.append(f"Equal Weight (QLIKE={eq_qlike:.4f}) is best or tied -- combination puzzle confirmed")

# C3: Rank-hybrid specific
rh_qlike = qlike_results['Rank Hybrid']
rh_spearman = spearman_results['Rank Hybrid']['rho']
conclusions.append(f"Rank-Level Hybrid: QLIKE={rh_qlike:.4f}, Spearman={rh_spearman:.4f} -- "
                   f"{'improves' if rh_spearman > spearman_results['GARCH']['rho'] else 'does not improve'} "
                   f"ranking vs GARCH")

# C4: Overall finding
mfgjr_qlike = qlike_results['MF-GJR(VIX)']
conclusions.append(f"MF-GJR(VIX) QLIKE={mfgjr_qlike:.4f} remains benchmark. "
                   f"Best overall: {best_qlike} (QLIKE={qlike_results[best_qlike]:.4f})")

results['conclusions'] = conclusions

# Save JSON
results_path = os.path.join(SCRIPT_DIR, 'k937_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"  Saved: {results_path}")

# Print conclusions
print("\n" + "=" * 60)
print("CONCLUSIONS")
print("=" * 60)
for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")
print("=" * 60)
print("K937 complete.")
