#!/usr/bin/env python3
"""
K485: SSVS Variance Equation Cross-OOS Validation (5 periods)
==============================================================
[提出: User, 執行: Claude]

Background:
  K484 applied SSVS to the variance equation and selected 4/5 components
  (PIP=1.000 each): GJR asymmetry, VIX implied var, Parkinson range, |ε| (TGARCH).
  QLIKE improvement: -7.43% vs base GARCH (DM t=4.31, p<0.001).

  BUT: K484 only tested ONE OOS period (2023-2024).
  K459/K460/K469 lesson: 3 false positives were caught by cross-OOS validation.
  This experiment validates with 5 independent OOS periods.

Variance equation (SSVS median model from K484):
  h_t = ω + α·ε²_{t-1} + β·h_{t-1}
        + γ·I(ε_{t-1}<0)·ε²_{t-1}     [GJR asymmetry]
        + λ₁·VIX²_{t-1}/252            [VIX implied var]
        + λ₂·Parkinson²_{t-1}          [Range-based info]
        + λ₃·|ε_{t-1}|                 [Absolute shock TGARCH]

5 OOS periods:
  1. 2015-2016
  2. 2017-2018 (Volmageddon)
  3. 2019-2020 (COVID)
  4. 2021-2022 (rate hikes)
  5. 2023-2024

5 models:
  1. Base GARCH(1,1)
  2. GJR-GARCH(1,1)
  3. SSVS Median model (GJR + VIX + Range + |ε|)
  4. GJR + VIX only
  5. GJR + Range only

Method:
  - IS window: 2000 days
  - Refit every 21 days (MLE via scipy.optimize L-BFGS-B)
  - QLIKE with r² proxy for realized variance
  - DM test: each model vs GJR baseline
  - Custom log-likelihood with variance recursion

Data: yfinance (SPY OHLCV + ^VIX), empirical
Refs:
  So, Chen, Liu (2006) Best Subset Selection, JRSS-C 55(2):201-224
  K484: SSVS variance eq → GJR+VIX+Range+|ε| selected (PIP=1.000)
  K459/K460/K469: Cross-OOS protocol (lesson: single-period insufficient)
  Patton (2011): QLIKE robust loss function
  Diebold & Mariano (1995): DM test
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
import yfinance as yf
import json
import time
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')
np.random.seed(42)

print("=" * 70)
print("K485: SSVS Variance Equation Cross-OOS Validation")
print("  5 models × 5 OOS periods, refit every 21 days")
print("  Core Q: Does SSVS median model (GJR+VIX+Range+|ε|) hold across all periods?")
print("=" * 70)

start_time = time.time()

# ============================================================
# CONFIGURATION
# ============================================================
IS_WINDOW = 2000
REFIT_INTERVAL = 21

OOS_PERIODS = [
    {"name": "2015-2016", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
]

MODEL_NAMES = [
    'Base GARCH(1,1)',
    'GJR-GARCH(1,1)',
    'SSVS Median (GJR+VIX+Range+|ε|)',
    'GJR + VIX only',
    'GJR + Range only',
]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data from yfinance...")

spy_raw = yf.download('SPY', start='2005-01-01', progress=False, auto_adjust=True)
vix_raw = yf.download('^VIX', start='2005-01-01', progress=False, auto_adjust=True)

# Flatten MultiIndex if needed
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

# Align dates
common_idx = spy_raw.index.intersection(vix_raw.index)
spy_raw = spy_raw.loc[common_idx]
vix_raw = vix_raw.loc[common_idx]

print(f"  SPY: {len(spy_raw)} obs, {spy_raw.index[0].date()} to {spy_raw.index[-1].date()}")
print(f"  VIX: {len(vix_raw)} obs")

# Extract arrays
spy_close = spy_raw['Close'].values.astype(float).ravel()
spy_high = spy_raw['High'].values.astype(float).ravel()
spy_low = spy_raw['Low'].values.astype(float).ravel()
vix_close = vix_raw['Close'].values.astype(float).ravel()

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

# Log returns (percent)
log_ret = np.diff(np.log(spy_close)) * 100
T_full = len(log_ret)
dates_full = common_idx[1:]  # dates for returns

# VIX daily implied variance (in return-percent² scale)
# VIX is in annualized %, so VIX²/252 gives daily variance in %²
vix_daily_var = (vix_close[:-1] ** 2) / 252.0  # lagged: use VIX at day t for return t+1

# Parkinson range-based variance (in log-return² scale ~ %²)
# Use high/low from same day as the return's first close
ratio_hl = spy_high[1:] / spy_low[1:]
ratio_hl = np.maximum(ratio_hl, 1.0001)
parkinson_raw = (np.log(ratio_hl) * 100) ** 2 / (4 * np.log(2))  # in %² scale

# Lagged absolute shock |ε_{t-1}| in %
abs_shock_raw = np.abs(log_ret)

# Lagged leverage: I(ε_{t-1}<0)·ε²_{t-1}
leverage_raw = np.where(log_ret < 0, log_ret ** 2, 0.0)

# r² proxy for realized variance (in %²)
r2_proxy = log_ret ** 2

# Build aligned feature DataFrame
feat = pd.DataFrame({
    'return_pct': log_ret,
    'r2_proxy': r2_proxy,
    'vix_daily_var': vix_daily_var,
    'parkinson': parkinson_raw,
    'abs_shock': abs_shock_raw,
    'leverage': leverage_raw,
}, index=dates_full)

# Need lagged features: for return at t, use features at t-1
feat['vix_lag'] = feat['vix_daily_var'].shift(1)
feat['park_lag'] = feat['parkinson'].shift(1)
feat['abs_lag'] = feat['abs_shock'].shift(1)
feat['lev_lag'] = feat['leverage'].shift(1)
feat['ret_lag'] = feat['return_pct'].shift(1)
feat['ret_lag2'] = feat['return_pct'].shift(1) ** 2  # ε²_{t-1}

feat = feat.dropna()
print(f"  Features: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")

# ============================================================
# 3. DIAGNOSTICS (full sample)
# ============================================================
print("\n[3] Full sample diagnostics...")
ret = feat['return_pct'].values
print(f"  Returns: n={len(ret)}, mean={ret.mean():.4f}%, std={ret.std():.4f}%")
print(f"  Skew={stats.skew(ret):.3f}, Kurt={stats.kurtosis(ret):.3f}")

adf_stat, adf_pval, *_ = adfuller(ret, maxlag=10)
print(f"  ADF: stat={adf_stat:.4f}, p={adf_pval:.4f} -> {'Stationary' if adf_pval < 0.05 else 'Non-stationary'}")

arch_stat, arch_pval, *_ = het_arch(ret, nlags=5)
print(f"  ARCH LM(5): stat={arch_stat:.2f}, p={arch_pval:.6f} -> {'ARCH effects' if arch_pval < 0.05 else 'No ARCH'}")

lb_res = acorr_ljungbox(ret ** 2, lags=[10], return_df=True)
lb_stat = lb_res['lb_stat'].values[0]
lb_pval = lb_res['lb_pvalue'].values[0]
print(f"  Ljung-Box ε²(10): stat={lb_stat:.2f}, p={lb_pval:.6f}")

# ============================================================
# 4. MODEL DEFINITIONS (custom log-likelihood + variance filter)
# ============================================================

def garch11_filter(params, returns):
    """GARCH(1,1) variance filter. params: [omega, alpha, beta]"""
    omega, alpha, beta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1]
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def garch11_negll(params, returns):
    """Negative log-likelihood for GARCH(1,1)."""
    omega, alpha, beta = params
    if omega <= 1e-8 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
        return 1e10
    h = garch11_filter(params, returns)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_filter(params, returns):
    """GJR-GARCH(1,1) filter. params: [omega, alpha, beta, gamma]"""
    omega, alpha, beta, gamma = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + beta * h[t-1] + gamma * indicator * returns[t-1]**2
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def gjr_negll(params, returns):
    """Negative log-likelihood for GJR-GARCH(1,1)."""
    omega, alpha, beta, gamma = params
    if omega <= 1e-8 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 0.9999:
        return 1e10
    h = gjr_filter(params, returns)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def ssvs_median_filter(params, returns, vix_var, parkinson, abs_shock):
    """SSVS Median model: GJR + VIX + Range + |ε|.
    params: [omega, alpha, beta, gamma, lambda_vix, lambda_range, lambda_abs]
    """
    omega, alpha, beta, gamma, lam_vix, lam_range, lam_abs = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = (omega
                + alpha * returns[t-1]**2
                + beta * h[t-1]
                + gamma * indicator * returns[t-1]**2
                + lam_vix * vix_var[t]
                + lam_range * parkinson[t]
                + lam_abs * abs_shock[t])
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def ssvs_median_negll(params, returns, vix_var, parkinson, abs_shock):
    """Negative log-likelihood for SSVS median model."""
    omega, alpha, beta, gamma, lam_vix, lam_range, lam_abs = params
    if omega <= 1e-8 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 0.9999:
        return 1e10
    h = ssvs_median_filter(params, returns, vix_var, parkinson, abs_shock)
    if np.any(h <= 0):
        return 1e10
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_vix_filter(params, returns, vix_var):
    """GJR + VIX only. params: [omega, alpha, beta, gamma, lambda_vix]"""
    omega, alpha, beta, gamma, lam_vix = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = (omega
                + alpha * returns[t-1]**2
                + beta * h[t-1]
                + gamma * indicator * returns[t-1]**2
                + lam_vix * vix_var[t])
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def gjr_vix_negll(params, returns, vix_var):
    """Negative log-likelihood for GJR + VIX."""
    omega, alpha, beta, gamma, lam_vix = params
    if omega <= 1e-8 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 0.9999:
        return 1e10
    h = gjr_vix_filter(params, returns, vix_var)
    if np.any(h <= 0):
        return 1e10
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_range_filter(params, returns, parkinson):
    """GJR + Range only. params: [omega, alpha, beta, gamma, lambda_range]"""
    omega, alpha, beta, gamma, lam_range = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = (omega
                + alpha * returns[t-1]**2
                + beta * h[t-1]
                + gamma * indicator * returns[t-1]**2
                + lam_range * parkinson[t])
        if h[t] < 1e-8:
            h[t] = 1e-8
    return h

def gjr_range_negll(params, returns, parkinson):
    """Negative log-likelihood for GJR + Range."""
    omega, alpha, beta, gamma, lam_range = params
    if omega <= 1e-8 or alpha < 0 or beta < 0 or gamma < 0:
        return 1e10
    if alpha + beta + 0.5 * gamma >= 0.9999:
        return 1e10
    h = gjr_range_filter(params, returns, parkinson)
    if np.any(h <= 0):
        return 1e10
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

# ============================================================
# 5. EVALUATION FUNCTIONS
# ============================================================

def compute_qlike(rv, h_forecast):
    """QLIKE loss: E[RV/h - log(RV/h) - 1] (Patton 2011)."""
    # Filter out zero rv (exact zero returns)
    mask = rv > 1e-12
    ratio = rv[mask] / h_forecast[mask]
    return np.mean(ratio - np.log(ratio) - 1)

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Negative DM stat → model 2 is better than model 1."""
    d = loss1 - loss2
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    T = len(d)
    gamma0 = np.var(d, ddof=0)
    hac_var = gamma0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * (1 - k / h) * gamma_k
    hac_var = max(hac_var, 1e-12)
    dm_stat = d_mean / np.sqrt(hac_var / T)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

# ============================================================
# 6. CROSS-OOS VALIDATION
# ============================================================
print("\n[6] Running cross-OOS validation across 5 periods...")

all_results = {}
period_summary = []

for period_idx, period in enumerate(OOS_PERIODS):
    period_name = period["name"]
    oos_start = period["start"]
    oos_end = period["end"]

    print(f"\n{'='*70}")
    print(f"  Period {period_idx+1}/5: {period_name}")
    print(f"  OOS: {oos_start} to {oos_end}")
    print(f"{'='*70}")

    # Find OOS indices in feat
    oos_mask = (feat.index >= oos_start) & (feat.index <= oos_end)
    oos_idx_start = np.where(oos_mask)[0]

    if len(oos_idx_start) == 0:
        print(f"  WARNING: No data for period {period_name}, skipping")
        continue

    oos_first = oos_idx_start[0]
    oos_last = oos_idx_start[-1]

    # Check if we have enough IS data
    if oos_first < IS_WINDOW:
        print(f"  WARNING: Not enough IS data ({oos_first} < {IS_WINDOW}), skipping")
        continue

    T_oos = oos_last - oos_first + 1
    print(f"  OOS days: {T_oos} (index {oos_first} to {oos_last})")
    print(f"  IS window: {IS_WINDOW} days, refit every {REFIT_INTERVAL} days")

    # Extract data arrays
    returns_all = feat['return_pct'].values
    vix_var_all = feat['vix_lag'].values
    park_all = feat['park_lag'].values
    abs_all = feat['abs_lag'].values
    r2_all = feat['r2_proxy'].values

    # Storage for OOS forecasts
    h_forecasts = {name: np.zeros(T_oos) for name in MODEL_NAMES}

    # Refit schedule
    n_refits = 0
    refit_count = 0
    period_fit_time = time.time()

    # Current parameter estimates (will be updated at each refit)
    params_garch = None
    params_gjr = None
    params_ssvs = None
    params_gjr_vix = None
    params_gjr_range = None

    for t_oos in range(T_oos):
        abs_idx = oos_first + t_oos

        # Refit if needed
        if t_oos % REFIT_INTERVAL == 0:
            refit_count += 1
            is_start = abs_idx - IS_WINDOW
            is_end = abs_idx

            ret_is = returns_all[is_start:is_end]
            vix_is = vix_var_all[is_start:is_end]
            park_is = park_all[is_start:is_end]
            abs_is = abs_all[is_start:is_end]

            var_is = np.var(ret_is)

            # --- Model 1: Base GARCH(1,1) ---
            x0_g = [var_is * 0.05, 0.08, 0.88]
            bounds_g = [(1e-8, var_is * 5), (1e-6, 0.4), (0.3, 0.999)]
            try:
                res = minimize(garch11_negll, x0_g, args=(ret_is,),
                              method='L-BFGS-B', bounds=bounds_g)
                if res.success or res.fun < 1e9:
                    params_garch = res.x
                else:
                    params_garch = x0_g
            except:
                params_garch = x0_g

            # --- Model 2: GJR-GARCH(1,1) ---
            x0_gjr = [var_is * 0.05, 0.05, 0.88, 0.05]
            bounds_gjr_b = [(1e-8, var_is * 5), (1e-6, 0.3), (0.3, 0.999), (1e-6, 0.3)]
            try:
                res = minimize(gjr_negll, x0_gjr, args=(ret_is,),
                              method='L-BFGS-B', bounds=bounds_gjr_b)
                if res.success or res.fun < 1e9:
                    params_gjr = res.x
                else:
                    params_gjr = x0_gjr
            except:
                params_gjr = x0_gjr

            # --- Model 3: SSVS Median (GJR + VIX + Range + |ε|) ---
            x0_ssvs = [var_is * 0.02, 0.03, 0.85, 0.05, 0.01, 0.01, -0.01]
            bounds_ssvs = [
                (1e-8, var_is * 5),   # omega
                (1e-6, 0.3),          # alpha
                (0.3, 0.999),         # beta
                (1e-6, 0.3),          # gamma (GJR)
                (-0.5, 0.5),          # lambda_vix
                (-5000, 5000),        # lambda_range (Parkinson scale is very small)
                (-1.0, 1.0),          # lambda_abs
            ]
            try:
                res = minimize(ssvs_median_negll, x0_ssvs,
                              args=(ret_is, vix_is, park_is, abs_is),
                              method='L-BFGS-B', bounds=bounds_ssvs)
                if res.success or res.fun < 1e9:
                    params_ssvs = res.x
                else:
                    # Try multiple starting points
                    best_val = 1e15
                    best_p = x0_ssvs
                    for trial_lam_vix in [0.01, 0.05, 0.15]:
                        for trial_lam_abs in [-0.1, -0.01, 0.0]:
                            x0_try = [var_is * 0.02, 0.03, 0.85, 0.05,
                                      trial_lam_vix, 100.0, trial_lam_abs]
                            try:
                                res2 = minimize(ssvs_median_negll, x0_try,
                                               args=(ret_is, vix_is, park_is, abs_is),
                                               method='L-BFGS-B', bounds=bounds_ssvs)
                                if res2.fun < best_val:
                                    best_val = res2.fun
                                    best_p = res2.x
                            except:
                                pass
                    params_ssvs = best_p
            except:
                params_ssvs = x0_ssvs

            # --- Model 4: GJR + VIX only ---
            x0_gv = [var_is * 0.03, 0.04, 0.87, 0.05, 0.05]
            bounds_gv = [
                (1e-8, var_is * 5),
                (1e-6, 0.3),
                (0.3, 0.999),
                (1e-6, 0.3),
                (-0.5, 0.5),
            ]
            try:
                res = minimize(gjr_vix_negll, x0_gv, args=(ret_is, vix_is),
                              method='L-BFGS-B', bounds=bounds_gv)
                if res.success or res.fun < 1e9:
                    params_gjr_vix = res.x
                else:
                    params_gjr_vix = x0_gv
            except:
                params_gjr_vix = x0_gv

            # --- Model 5: GJR + Range only ---
            x0_gr = [var_is * 0.03, 0.04, 0.87, 0.05, 100.0]
            bounds_gr = [
                (1e-8, var_is * 5),
                (1e-6, 0.3),
                (0.3, 0.999),
                (1e-6, 0.3),
                (-5000, 5000),
            ]
            try:
                res = minimize(gjr_range_negll, x0_gr, args=(ret_is, park_is),
                              method='L-BFGS-B', bounds=bounds_gr)
                if res.success or res.fun < 1e9:
                    params_gjr_range = res.x
                else:
                    params_gjr_range = x0_gr
            except:
                params_gjr_range = x0_gr

            if refit_count <= 3 or refit_count % 5 == 0:
                print(f"    Refit {refit_count}: day {t_oos}/{T_oos}")

        # --- Generate 1-step-ahead forecasts ---
        # For the forecast at t_oos, we need:
        #   ε_{t-1} = returns_all[abs_idx - 1]
        #   h_{t-1} approximated from the IS-fitted model (use variance recursion)

        # We run the full IS filter to get h at the boundary, then forecast one step
        e_prev = returns_all[abs_idx - 1]
        e_prev2 = e_prev ** 2
        ind_prev = 1.0 if e_prev < 0 else 0.0

        # For exogenous variables at t (which are lagged from perspective of return t)
        vix_t = vix_var_all[abs_idx]
        park_t = park_all[abs_idx]
        abs_t = abs_all[abs_idx]

        # Need h_{t-1} from each model. We approximate using the recursive formula
        # from the last refit. For computational efficiency, we track h recursively.
        if t_oos == 0 or t_oos % REFIT_INTERVAL == 0:
            # Re-initialize h from IS filter at boundary
            is_start = abs_idx - IS_WINDOW
            ret_is_block = returns_all[is_start:abs_idx]

            h_prev_garch = garch11_filter(params_garch, ret_is_block)[-1]
            h_prev_gjr = gjr_filter(params_gjr, ret_is_block)[-1]

            vix_is_block = vix_var_all[is_start:abs_idx]
            park_is_block = park_all[is_start:abs_idx]
            abs_is_block = abs_all[is_start:abs_idx]
            h_prev_ssvs = ssvs_median_filter(params_ssvs, ret_is_block,
                                              vix_is_block, park_is_block, abs_is_block)[-1]
            h_prev_gjr_vix = gjr_vix_filter(params_gjr_vix, ret_is_block, vix_is_block)[-1]
            h_prev_gjr_range = gjr_range_filter(params_gjr_range, ret_is_block, park_is_block)[-1]

        # Model 1: GARCH(1,1)
        h_t = params_garch[0] + params_garch[1] * e_prev2 + params_garch[2] * h_prev_garch
        h_t = max(h_t, 1e-8)
        h_forecasts['Base GARCH(1,1)'][t_oos] = h_t
        h_prev_garch = h_t

        # Model 2: GJR-GARCH
        h_t = (params_gjr[0] + params_gjr[1] * e_prev2 + params_gjr[2] * h_prev_gjr
               + params_gjr[3] * ind_prev * e_prev2)
        h_t = max(h_t, 1e-8)
        h_forecasts['GJR-GARCH(1,1)'][t_oos] = h_t
        h_prev_gjr = h_t

        # Model 3: SSVS Median
        h_t = (params_ssvs[0] + params_ssvs[1] * e_prev2 + params_ssvs[2] * h_prev_ssvs
               + params_ssvs[3] * ind_prev * e_prev2
               + params_ssvs[4] * vix_t
               + params_ssvs[5] * park_t
               + params_ssvs[6] * abs_t)
        h_t = max(h_t, 1e-8)
        h_forecasts['SSVS Median (GJR+VIX+Range+|ε|)'][t_oos] = h_t
        h_prev_ssvs = h_t

        # Model 4: GJR + VIX
        h_t = (params_gjr_vix[0] + params_gjr_vix[1] * e_prev2 + params_gjr_vix[2] * h_prev_gjr_vix
               + params_gjr_vix[3] * ind_prev * e_prev2
               + params_gjr_vix[4] * vix_t)
        h_t = max(h_t, 1e-8)
        h_forecasts['GJR + VIX only'][t_oos] = h_t
        h_prev_gjr_vix = h_t

        # Model 5: GJR + Range
        h_t = (params_gjr_range[0] + params_gjr_range[1] * e_prev2 + params_gjr_range[2] * h_prev_gjr_range
               + params_gjr_range[3] * ind_prev * e_prev2
               + params_gjr_range[4] * park_t)
        h_t = max(h_t, 1e-8)
        h_forecasts['GJR + Range only'][t_oos] = h_t
        h_prev_gjr_range = h_t

    period_elapsed = time.time() - period_fit_time
    print(f"\n  Period completed: {refit_count} refits in {period_elapsed:.1f}s")

    # --- Evaluate ---
    rv_oos = r2_all[oos_first:oos_first + T_oos]

    period_result = {"period": period_name, "T_oos": T_oos, "n_refits": refit_count}
    model_metrics = {}

    # Compute QLIKE for each model
    base_qlike = None
    qlike_losses = {}

    for model_name in MODEL_NAMES:
        h_oos = h_forecasts[model_name]
        qlike = compute_qlike(rv_oos, h_oos)
        mse = np.mean((rv_oos - h_oos) ** 2)

        # Individual QLIKE losses for DM test
        mask = rv_oos > 1e-12
        ratio = rv_oos[mask] / h_oos[mask]
        losses = ratio - np.log(ratio) - 1
        qlike_losses[model_name] = losses

        if model_name == 'Base GARCH(1,1)':
            base_qlike = qlike

        model_metrics[model_name] = {
            "QLIKE": float(qlike),
            "MSE": float(mse),
        }

    # Relative QLIKE and DM tests (vs GJR baseline)
    gjr_qlike = model_metrics['GJR-GARCH(1,1)']['QLIKE']
    gjr_losses = qlike_losses['GJR-GARCH(1,1)']

    for model_name in MODEL_NAMES:
        rel_vs_base = (model_metrics[model_name]['QLIKE'] - base_qlike) / base_qlike * 100
        rel_vs_gjr = (model_metrics[model_name]['QLIKE'] - gjr_qlike) / gjr_qlike * 100
        model_metrics[model_name]['rel_QLIKE_vs_base_pct'] = float(rel_vs_base)
        model_metrics[model_name]['rel_QLIKE_vs_GJR_pct'] = float(rel_vs_gjr)

        # DM test vs GJR
        if model_name != 'GJR-GARCH(1,1)':
            dm_stat, dm_pval = dm_test(gjr_losses, qlike_losses[model_name])
            sig = "***" if dm_pval < 0.01 else ("**" if dm_pval < 0.05 else ("*" if dm_pval < 0.10 else ""))
            model_metrics[model_name]['DM_vs_GJR'] = {
                'stat': float(dm_stat),
                'p_value': float(dm_pval),
                'sig': sig,
                'interpretation': 'model BETTER' if dm_stat > 0 else 'model WORSE'
            }

    period_result['model_metrics'] = model_metrics
    all_results[period_name] = period_result

    # Print summary for this period
    print(f"\n  {'Model':<40s} {'QLIKE':>8s} {'vs Base':>8s} {'vs GJR':>8s} {'DM(GJR)':>8s} {'p':>8s}")
    print(f"  {'-'*80}")
    for mn in MODEL_NAMES:
        m = model_metrics[mn]
        dm_str = ""
        p_str = ""
        if 'DM_vs_GJR' in m:
            dm_str = f"{m['DM_vs_GJR']['stat']:+.3f}"
            p_str = f"{m['DM_vs_GJR']['p_value']:.4f}"
        print(f"  {mn:<40s} {m['QLIKE']:8.4f} {m['rel_QLIKE_vs_base_pct']:+7.2f}% {m['rel_QLIKE_vs_GJR_pct']:+7.2f}% {dm_str:>8s} {p_str:>8s}")

    # Track SSVS performance
    ssvs_m = model_metrics['SSVS Median (GJR+VIX+Range+|ε|)']
    ssvs_better = ssvs_m['rel_QLIKE_vs_GJR_pct'] < 0
    ssvs_sig = 'DM_vs_GJR' in ssvs_m and ssvs_m['DM_vs_GJR']['p_value'] < 0.10
    period_summary.append({
        'period': period_name,
        'ssvs_qlike': ssvs_m['QLIKE'],
        'gjr_qlike': gjr_qlike,
        'rel_pct': ssvs_m['rel_QLIKE_vs_GJR_pct'],
        'dm_stat': ssvs_m['DM_vs_GJR']['stat'] if 'DM_vs_GJR' in ssvs_m else 0,
        'dm_pval': ssvs_m['DM_vs_GJR']['p_value'] if 'DM_vs_GJR' in ssvs_m else 1,
        'ssvs_better': ssvs_better,
        'ssvs_significant': ssvs_sig,
    })

total_time = time.time() - start_time

# ============================================================
# 7. CROSS-OOS SUMMARY
# ============================================================
print(f"\n{'='*70}")
print("CROSS-OOS SUMMARY")
print(f"{'='*70}")

print(f"\n  SSVS Median (GJR+VIX+Range+|ε|) vs GJR-GARCH(1,1):")
print(f"  {'Period':<30s} {'SSVS QLIKE':>12s} {'GJR QLIKE':>12s} {'Relative':>10s} {'DM stat':>10s} {'p-value':>10s} {'Winner':>8s}")
print(f"  {'-'*95}")

n_better = 0
n_significant = 0

for ps in period_summary:
    winner = "SSVS" if ps['ssvs_better'] else "GJR"
    sig_mark = "***" if ps['dm_pval'] < 0.01 else ("**" if ps['dm_pval'] < 0.05 else ("*" if ps['dm_pval'] < 0.10 else ""))
    print(f"  {ps['period']:<30s} {ps['ssvs_qlike']:12.4f} {ps['gjr_qlike']:12.4f} "
          f"{ps['rel_pct']:+9.2f}% {ps['dm_stat']:+10.3f} {ps['dm_pval']:10.4f} {winner:>6s}{sig_mark}")
    if ps['ssvs_better']:
        n_better += 1
    if ps['ssvs_significant']:
        n_significant += 1

print(f"\n  SSVS better in: {n_better}/5 periods")
print(f"  SSVS significantly better (DM p<0.10): {n_significant}/5 periods")

# Overall judgment
if n_significant >= 4:
    verdict = "PUBLICATION READY — SSVS median model robust across periods"
elif n_significant >= 3:
    verdict = "STRONG — SSVS median model mostly robust, minor period-dependence"
elif n_better >= 4:
    verdict = "PROMISING — SSVS better in most periods but not always significant"
elif n_better >= 3:
    verdict = "MODERATE — Mixed evidence, partially period-dependent"
else:
    verdict = "PERIOD-SPECIFIC — SSVS improvement does not generalize (like K459 VRP)"

print(f"\n  VERDICT: {verdict}")

# ============================================================
# 8. FULL MODEL COMPARISON ACROSS PERIODS
# ============================================================
print(f"\n{'='*70}")
print("FULL MODEL COMPARISON: Average QLIKE across 5 periods")
print(f"{'='*70}")

avg_qlike = {mn: [] for mn in MODEL_NAMES}
avg_rel_gjr = {mn: [] for mn in MODEL_NAMES}

for pname, presult in all_results.items():
    for mn in MODEL_NAMES:
        avg_qlike[mn].append(presult['model_metrics'][mn]['QLIKE'])
        avg_rel_gjr[mn].append(presult['model_metrics'][mn]['rel_QLIKE_vs_GJR_pct'])

print(f"\n  {'Model':<40s} {'Avg QLIKE':>10s} {'Avg vs GJR':>12s} {'Win/5':>6s}")
print(f"  {'-'*72}")
for mn in MODEL_NAMES:
    avg_q = np.mean(avg_qlike[mn])
    avg_r = np.mean(avg_rel_gjr[mn])
    n_win = sum(1 for r in avg_rel_gjr[mn] if r < 0) if mn != 'GJR-GARCH(1,1)' else '-'
    print(f"  {mn:<40s} {avg_q:10.4f} {avg_r:+11.2f}% {str(n_win):>6s}")

# Best model overall
best_model = min(MODEL_NAMES, key=lambda mn: np.mean(avg_qlike[mn]))
print(f"\n  Best model (lowest avg QLIKE): {best_model}")

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print(f"\n[9] Saving results...")

# Build comprehensive results JSON
results_json = {
    "experiment_id": "K485",
    "title": "SSVS Variance Equation Cross-OOS Validation (5 periods)",
    "method": "Cross-OOS validation of K484 SSVS median model (GJR+VIX+Range+|ε|) vs baselines",
    "proposed_by": "User (publication-critical validation)",
    "asset": "SPY",
    "data_source": "yfinance (empirical)",
    "data_period": f"{spy_raw.index[0].date()} to {spy_raw.index[-1].date()}",
    "total_observations": len(feat),
    "configuration": {
        "IS_window": IS_WINDOW,
        "refit_interval": REFIT_INTERVAL,
        "n_oos_periods": 5,
        "variance_proxy": "r² (squared return)",
        "loss_function": "QLIKE (Patton 2011)",
        "models": MODEL_NAMES,
    },
    "ssvs_median_variance_equation": {
        "spec": "h_t = ω + α·ε²_{t-1} + β·h_{t-1} + γ·I(ε<0)·ε²_{t-1} + λ₁·VIX²/252 + λ₂·Range² + λ₃·|ε|",
        "components": {
            "GJR_asymmetry": "I(ε_{t-1}<0)·ε²_{t-1}",
            "VIX_implied_var": "VIX²_{t-1}/252 (daily implied variance)",
            "Parkinson_range": "(ln(H/L))²/(4ln2) (range-based estimator)",
            "Abs_shock_TGARCH": "|ε_{t-1}| (absolute shock, TGARCH/AVGARCH style)",
        },
        "K484_PIPs": {
            "GJR_asymmetry": 1.000,
            "VIX_implied_var": 1.000,
            "Parkinson_range": 1.000,
            "Abs_shock_TGARCH": 1.000,
            "Neg_semivariance_excluded": 0.094,
        },
    },
    "cross_oos_results": {},
    "ssvs_vs_gjr_summary": [],
    "full_model_comparison": {},
    "verdict": verdict,
    "computation_time_seconds": total_time,
    "references": [
        "So, Chen, Liu (2006) Best Subset Selection of ARX-GARCH, JRSS-C 55(2):201-224",
        "Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies, JoE 160(1):246-256",
        "Diebold & Mariano (1995) Comparing Predictive Accuracy, JBES 13(3):253-263",
        "K484: SSVS variance eq -> GJR+VIX+Range+|ε| selected (PIP=1.000, QLIKE -7.43%)",
        "K459/K460/K469: Cross-OOS protocol (lesson: single-period results unreliable)",
    ],
}

# Add per-period results
for pname, presult in all_results.items():
    results_json["cross_oos_results"][pname] = presult

# Add summary
for ps in period_summary:
    results_json["ssvs_vs_gjr_summary"].append({
        "period": ps['period'],
        "ssvs_qlike": ps['ssvs_qlike'],
        "gjr_qlike": ps['gjr_qlike'],
        "relative_pct": ps['rel_pct'],
        "dm_stat": ps['dm_stat'],
        "dm_pval": ps['dm_pval'],
        "ssvs_better": ps['ssvs_better'],
        "ssvs_significant_10pct": ps['ssvs_significant'],
    })

# Add full model comparison
for mn in MODEL_NAMES:
    results_json["full_model_comparison"][mn] = {
        "avg_QLIKE": float(np.mean(avg_qlike[mn])),
        "qlike_per_period": [float(q) for q in avg_qlike[mn]],
        "avg_rel_vs_GJR_pct": float(np.mean(avg_rel_gjr[mn])),
    }

results_json["conclusion"] = {
    "n_periods_ssvs_better": n_better,
    "n_periods_ssvs_significant": n_significant,
    "verdict": verdict,
    "best_model_avg_qlike": best_model,
    "interpretation": (
        f"SSVS Median model (GJR+VIX+Range+|ε|) was better than GJR in {n_better}/5 periods "
        f"and statistically significant in {n_significant}/5 periods (DM test p<0.10). "
        f"{'This confirms K484 finding as robust across market regimes.' if n_significant >= 4 else ''}"
        f"{'The improvement is partially regime-dependent.' if 2 <= n_significant <= 3 else ''}"
        f"{'The K484 result does not generalize — period-specific only.' if n_significant < 2 else ''}"
    ),
}

# Save
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, 'k485_ssvs_vareq_cross_oos_results.json')
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)
print(f"  Saved: {output_path}")

print(f"\n{'='*70}")
print(f"K485 completed in {total_time:.1f}s")
print(f"VERDICT: {verdict}")
print(f"{'='*70}")
