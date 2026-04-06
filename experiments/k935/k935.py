"""
K935: Gap-Adjusted CARR — Fixing Parkinson Overnight Bias
Compare 4 range estimators as CARR targets:
  1. Parkinson (1980) — ignores overnight gap
  2. Garman-Klass (1980) — includes Open-Close
  3. Rogers-Satchell (1991) — allows non-zero drift
  4. Yang-Zhang (2000) — includes overnight + open jump + intraday

Hypotheses:
  H1: GK/RS/YZ CARR have lower QLIKE on r² than Parkinson CARR
  H2: Gap-adjusted CARR may approach GARCH calibration

References:
  Parkinson (1980) "The Extreme Value Method for Estimating the Variance of the Rate of Return"
  Garman & Klass (1980) "On the Estimation of Security Price Volatilities from Historical Data"
  Rogers & Satchell (1991) "Estimating Variance from High, Low and Closing Prices"
  Yang & Zhang (2000) "Drift Independent Volatility Estimation"
  Chou (2005) "Forecasting Financial Volatilities with Extreme Values"
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies" J. Econometrics 160

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2004-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000, Refit: every 21 trading days

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

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K935: Gap-Adjusted CARR — Fixing Parkinson Overnight Bias")
print("=" * 60)

print("\n[1/7] Downloading data...")
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

# Overnight return: log(Open_t / Close_{t-1})
spy['overnight_return'] = spy['log_O'] - spy['log_C'].shift(1)

# ============================================================
# 2. RANGE ESTIMATORS
# ============================================================
print("\n[2/7] Computing range estimators...")

# --- Parkinson (1980) ---
# sigma^2_P = (H-L)^2 / (4*ln2)
spy['range_parkinson'] = (spy['log_H'] - spy['log_L'])**2 / (4 * np.log(2))

# --- Garman-Klass (1980) ---
# sigma^2_GK = 0.5*(H-L)^2 - (2*ln2 - 1)*(C-O)^2
spy['range_gk'] = (0.5 * (spy['log_H'] - spy['log_L'])**2
                   - (2*np.log(2) - 1) * (spy['log_C'] - spy['log_O'])**2)

# --- Rogers-Satchell (1991) ---
# sigma^2_RS = (H-C)(H-O) + (L-C)(L-O)
spy['range_rs'] = ((spy['log_H'] - spy['log_C']) * (spy['log_H'] - spy['log_O'])
                  + (spy['log_L'] - spy['log_C']) * (spy['log_L'] - spy['log_O']))

# --- Yang-Zhang (2000) ---
# sigma^2_YZ = sigma^2_overnight + k * sigma^2_open + (1-k) * sigma^2_RS
# where k = 0.34 / (1.34 + (n+1)/(n-1))  (n = window size for rolling)
# sigma^2_overnight = (O_t - C_{t-1})^2 in log prices
# sigma^2_open = (H - O)^2 + (L - O)^2 ... actually:
# Actually, let's use the point estimate per Yang-Zhang:
# For daily point estimates (single-day), YZ reduces to:
# sigma^2_YZ = overnight^2 + k * open_var_proxy + (1-k) * RS
# We use a simplified approach: overnight^2 + RS (which captures gap + intraday)
# The full YZ requires rolling estimation of variance components.
# For CARR modeling, we compute a composite single-day variance:
spy['overnight_sq'] = spy['overnight_return']**2
# k = 0.34/(1.34 + 2) = 0.34/3.34 ≈ 0.1018 (for large n)
k_yz = 0.34 / (1.34 + 2.0)  # asymptotic k
# sigma^2_open proxy: Var of intraday range relative to open
spy['open_var'] = ((spy['log_H'] - spy['log_O'])**2 + (spy['log_L'] - spy['log_O'])**2)
spy['range_yz'] = spy['overnight_sq'] + k_yz * spy['open_var'] + (1 - k_yz) * spy['range_rs']

# Add VIX
vix_close = vix['Close'].rename('VIX')
spy = spy.join(vix_close, how='left')
spy['VIX'] = spy['VIX'].ffill()
spy['log_VIX'] = np.log(spy['VIX'])

# Drop NaN
spy = spy.dropna(subset=['range_parkinson', 'range_gk', 'range_rs', 'range_yz',
                          'log_return', 'r2', 'VIX', 'overnight_return'])

print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Handle negative/zero values in GK and RS
# GK can be negative when close-to-open range dominates
# RS can be negative when drift is large
n_neg_gk = (spy['range_gk'] <= 0).sum()
n_neg_rs = (spy['range_rs'] <= 0).sum()
n_neg_yz = (spy['range_yz'] <= 0).sum()
print(f"\n  Negative values: GK={n_neg_gk}, RS={n_neg_rs}, YZ={n_neg_yz}")

# Floor at small positive value for CARR estimation
FLOOR = 1e-10
for col in ['range_parkinson', 'range_gk', 'range_rs', 'range_yz']:
    spy[col] = np.maximum(spy[col], FLOOR)

# Descriptive statistics
print("\n  Descriptive Statistics (mean, std, min, max):")
for name, col in [('Parkinson', 'range_parkinson'), ('GK', 'range_gk'),
                   ('RS', 'range_rs'), ('YZ', 'range_yz'), ('r2', 'r2')]:
    vals = spy[col]
    print(f"    {name:10s}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
          f"min={vals.min():.6f}, max={vals.max():.6f}")

# Correlation matrix among estimators and r²
estimator_cols = ['range_parkinson', 'range_gk', 'range_rs', 'range_yz', 'r2']
corr_matrix = spy[estimator_cols].corr()
print("\n  Correlation matrix:")
for c1 in estimator_cols:
    row = [f"{corr_matrix.loc[c1, c2]:.4f}" for c2 in estimator_cols]
    print(f"    {c1:18s}: {' '.join(row)}")

# ============================================================
# 3. MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3/7] Implementing models...")


def carr_fit(ranges, max_iter=500):
    """Fit CARR(1,1) with Exponential innovation.
    Range_t = lambda_t * epsilon_t, epsilon_t ~ Exp(1)
    lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1}
    Log-likelihood: sum(-log(lambda_t) - Range_t / lambda_t)
    """
    T = len(ranges)
    mean_r = np.mean(ranges)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(T)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for t in range(1, T):
            lam[t] = omega + alpha * ranges[t - 1] + beta * lam[t - 1]
            if lam[t] <= 1e-10:
                lam[t] = 1e-10
        ll = -np.log(lam) - ranges / lam
        return -np.sum(ll[10:])

    omega0 = mean_r * 0.05
    alpha0 = 0.10
    beta0 = 0.85
    x0 = [omega0, alpha0, beta0]

    bounds = [(1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.90), (0.15, 0.80), (0.08, 0.88)]:
            x0_alt = [mean_r * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def carr_forecast_oos(params, ranges):
    """One-step-ahead CARR forecast (recursive). Returns T forecasts."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(ranges)
    lam = np.zeros(T + 1)
    lam[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        lam[t + 1] = omega + alpha * ranges[t] + beta * lam[t]
        if lam[t + 1] <= 1e-10:
            lam[t + 1] = 1e-10
    return lam[1:]  # forecast for t=1,...,T (uses info up to t-1)


def garch_fit(returns, max_iter=500):
    """Fit GARCH(1,1) via MLE with Normal innovations."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t - 1] ** 2 + beta * h[t - 1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.08, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.92), (0.12, 0.85), (0.03, 0.95)]:
            x0_alt = [mean_r2 * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def garch_forecast_oos(params, returns):
    """One-step-ahead GARCH forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        h[t + 1] = omega + alpha * returns[t] ** 2 + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


def mf_gjr_fit(returns, log_vix, max_iter=500):
    """MF-GJR(VIX) from K889 — best known model."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        theta0, theta1, omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5 * gamma + beta) >= 0.9999:
            return 1e10

        tau = np.exp(theta0 + theta1 * log_vix)
        tau = np.maximum(tau, 1e-16)

        g = np.zeros(T)
        g[0] = 1.0
        for t in range(1, T):
            shock = r[t - 1] ** 2 / tau[t - 1]
            asym = shock * (r[t - 1] < 0)
            g[t] = omega + alpha * shock + gamma * asym + beta * g[t - 1]
            if g[t] <= 1e-10:
                g[t] = 1e-10

        h = tau * g
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = 0.02
    x0 = [np.log(mean_r2) - 0.5 * np.mean(log_vix), 0.5, omega0, 0.02, 0.10, 0.85]
    bounds = [(None, None), (0.0, 3.0), (1e-8, None), (0.0, 0.5), (0.0, 0.5), (0.3, 0.9999)]

    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for t1 in [0.3, 0.7, 1.0]:
            x0_alt = [x0[0], t1, 0.05, 0.02, 0.10, 0.85]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    theta0, theta1, omega, alpha, gamma, beta = result.x
    return {'theta0': theta0, 'theta1': theta1, 'omega': omega,
            'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta,
            'converged': result.success, 'loglik': -result.fun}


def mf_gjr_forecast_oos(params, returns, log_vix):
    """One-step-ahead MF-GJR forecast (recursive)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)

    tau = np.exp(theta0 + theta1 * log_vix)
    tau = np.maximum(tau, 1e-16)

    g = np.zeros(T + 1)
    g[0] = 1.0
    for t in range(T):
        shock = returns[t] ** 2 / tau[t]
        asym = shock * (returns[t] < 0)
        g[t + 1] = omega + alpha * shock + gamma * asym + beta * g[t]
        if g[t + 1] <= 1e-10:
            g[t + 1] = 1e-10

    h = tau * g[1:]
    return h


# ============================================================
# 4. RANGE-TO-VARIANCE CONVERSION
# ============================================================
print("\n[4/7] Setting up range-to-variance conversion...")

# Key insight from K934: Parkinson CARR predicts lambda (conditional mean of range),
# and the conversion to sigma^2 introduces bias because Parkinson assumes continuous paths.
#
# For each estimator, the CARR predicts E[estimator_t | F_{t-1}] = lambda_t.
# The conversion to sigma^2 depends on the estimator:
#
# Parkinson: sigma^2 = lambda^2 / (4*ln2)  ← lambda = E[log(H/L)], so lambda is in range units
#            Actually, if we use sigma^2_P = (H-L)^2/(4*ln2) as the CARR target,
#            then lambda = E[sigma^2_P], so no conversion needed — lambda IS the variance estimate
#
# GK/RS/YZ: These are already variance estimators, so lambda = E[sigma^2_estimator]
#           No conversion needed — lambda IS the variance estimate
#
# So for ALL estimators used as CARR targets in variance form, lambda = E[variance].
# The QLIKE on r^2 comparison is direct: predicted = lambda_t (from CARR)

# For Parkinson CARR on log_range (not variance):
# Need to use log_range as CARR target and convert: sigma^2 = lambda^2 / (4*ln2)
# But K934 used parkinson_var as target directly, let me follow that approach.

# All CARR models use variance-form range as target.
# Prediction = lambda_t = conditional mean of variance-form range estimator.

ESTIMATORS = {
    'Parkinson': 'range_parkinson',
    'GK': 'range_gk',
    'RS': 'range_rs',
    'YZ': 'range_yz',
}

# ============================================================
# 5. OOS FORECASTING
# ============================================================
print("\n[5/7] Running OOS forecasting (this may take a few minutes)...")

oos_start = '2016-01-01'
oos_mask = spy.index >= oos_start
oos_idx = spy.index[oos_mask]
n_oos = len(oos_idx)
print(f"  OOS period: {oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}")
print(f"  OOS days: {n_oos}")

WINDOW = 2000
REFIT = 21

# Storage for forecasts
forecasts = {}
for est_name in ESTIMATORS:
    forecasts[f'CARR_{est_name}'] = np.full(n_oos, np.nan)
forecasts['GARCH'] = np.full(n_oos, np.nan)
forecasts['MF_GJR'] = np.full(n_oos, np.nan)

# Get all data arrays
returns_all = spy['log_return'].values
r2_all = spy['r2'].values
log_vix_all = spy['log_VIX'].values
range_arrays = {name: spy[col].values for name, col in ESTIMATORS.items()}

# Find the position of first OOS observation
first_oos_pos = np.searchsorted(spy.index, pd.Timestamp(oos_start))

# Track model parameters
model_params = {}
n_refits = 0

for i in range(n_oos):
    t = first_oos_pos + i  # position in full array

    # Refit every REFIT days
    if i % REFIT == 0:
        train_start = max(0, t - WINDOW)
        train_end = t  # exclusive

        # CARR models for each estimator
        for est_name, col_name in ESTIMATORS.items():
            ranges_train = range_arrays[est_name][train_start:train_end]
            params = carr_fit(ranges_train)
            model_params[f'CARR_{est_name}'] = params

        # GARCH
        returns_train = returns_all[train_start:train_end]
        garch_params = garch_fit(returns_train)
        model_params['GARCH'] = garch_params

        # MF-GJR
        log_vix_train = log_vix_all[train_start:train_end]
        mf_gjr_params = mf_gjr_fit(returns_train, log_vix_train)
        model_params['MF_GJR'] = mf_gjr_params

        n_refits += 1
        if n_refits % 20 == 0:
            print(f"    Refit {n_refits}: t={i}/{n_oos}")

    # Forecasts using recursive one-step-ahead
    # All models use data up to t-1 to forecast t

    # CARR models: lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1}
    for est_name in ESTIMATORS:
        p = model_params[f'CARR_{est_name}']
        ranges_history = range_arrays[est_name][train_start:t]
        fcast = carr_forecast_oos(p, ranges_history)
        forecasts[f'CARR_{est_name}'][i] = fcast[-1]  # last element = forecast for t

    # GARCH: h_t = omega + alpha * r^2_{t-1} + beta * h_{t-1}
    p = model_params['GARCH']
    ret_history = returns_all[train_start:t]
    fcast = garch_forecast_oos(p, ret_history)
    forecasts['GARCH'][i] = fcast[-1]

    # MF-GJR: uses VIX as well
    p = model_params['MF_GJR']
    ret_history = returns_all[train_start:t]
    vix_history = log_vix_all[train_start:t]
    fcast = mf_gjr_forecast_oos(p, ret_history, vix_history)
    forecasts['MF_GJR'][i] = fcast[-1]

print(f"  Total refits: {n_refits}")

# ============================================================
# 6. EVALUATION
# ============================================================
print("\n[6/7] Evaluating models...")

# Target: r² (Patton 2011 proxy-robust)
actual_r2 = r2_all[first_oos_pos:first_oos_pos + n_oos]

# Also compute actual range-based variances for native target comparison
actual_ranges = {}
for est_name, col_name in ESTIMATORS.items():
    actual_ranges[est_name] = range_arrays[est_name][first_oos_pos:first_oos_pos + n_oos]

# Model names for evaluation
all_models = [f'CARR_{name}' for name in ESTIMATORS] + ['GARCH', 'MF_GJR']

# --- Layer 1: Native target QLIKE ---
print("\n  Layer 1: Native Target QLIKE")
native_qlike = {}
for est_name in ESTIMATORS:
    model_name = f'CARR_{est_name}'
    fcast = forecasts[model_name]
    actual = actual_ranges[est_name]
    valid = np.isfinite(fcast) & np.isfinite(actual) & (fcast > 0) & (actual > 0)
    q = qlike(actual[valid], fcast[valid])
    native_qlike[model_name] = q
    print(f"    {model_name:18s} on {est_name:10s}: QLIKE={q:.6f}")

# GARCH on r²
valid = np.isfinite(forecasts['GARCH']) & np.isfinite(actual_r2) & (forecasts['GARCH'] > 0) & (actual_r2 > 0)
q = qlike(actual_r2[valid], forecasts['GARCH'][valid])
native_qlike['GARCH'] = q
print(f"    {'GARCH':18s} on {'r2':10s}: QLIKE={q:.6f}")

valid = np.isfinite(forecasts['MF_GJR']) & np.isfinite(actual_r2) & (forecasts['MF_GJR'] > 0) & (actual_r2 > 0)
q = qlike(actual_r2[valid], forecasts['MF_GJR'][valid])
native_qlike['MF_GJR'] = q
print(f"    {'MF_GJR':18s} on {'r2':10s}: QLIKE={q:.6f}")

# --- Layer 2: QLIKE on r² (Patton 2011 — fair cross-model comparison) ---
print("\n  Layer 2: QLIKE on r² (Patton 2011)")
qlike_r2 = {}
for model_name in all_models:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_r2) & (fcast > 0) & (actual_r2 > 0)
    q = qlike(actual_r2[valid], fcast[valid])
    qlike_r2[model_name] = q
    print(f"    {model_name:18s}: QLIKE={q:.6f}")

# Ranking
ranking = sorted(qlike_r2.items(), key=lambda x: x[1])
print("\n  Ranking (lower = better):")
for rank, (model, q) in enumerate(ranking, 1):
    print(f"    {rank}. {model:18s}: {q:.6f}")

# --- Layer 3: Spearman rank correlation ---
print("\n  Layer 3: Spearman rank correlation with r²")
spearman_results = {}
for model_name in all_models:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_r2)
    rho, pval = stats.spearmanr(fcast[valid], actual_r2[valid])
    spearman_results[model_name] = {'rho': round(rho, 4), 'pval': round(pval, 6)}
    print(f"    {model_name:18s}: rho={rho:.4f}, p={pval:.2e}")

# --- Layer 4: DM tests (Harvey |t| > 3.0) ---
print("\n  Layer 4: DM tests (Harvey threshold |t| > 3.0)")
dm_results = {}
for i, (m1, _) in enumerate(ranking):
    for m2, _ in ranking[i+1:]:
        f1 = forecasts[m1]
        f2 = forecasts[m2]
        valid = (np.isfinite(f1) & np.isfinite(f2) & np.isfinite(actual_r2)
                 & (f1 > 0) & (f2 > 0) & (actual_r2 > 0))
        loss1 = qlike_pointwise(actual_r2[valid], f1[valid])
        loss2 = qlike_pointwise(actual_r2[valid], f2[valid])
        t_stat, p_val = dm_test(loss1, loss2)

        significant = abs(t_stat) > 3.0
        if t_stat < 0:
            winner = m1 if significant else "n.s."
        else:
            winner = m2 if significant else "n.s."

        key = f"{m1} vs {m2}"
        dm_results[key] = {
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6),
            'significant': significant,
            'winner': winner
        }
        sig_marker = "***" if significant else ""
        print(f"    {key:40s}: t={t_stat:7.4f}, p={p_val:.4f} {sig_marker} → {winner}")

# --- Supplementary: QLIKE on Parkinson variance ---
print("\n  Supplementary: QLIKE on Parkinson variance")
actual_pk = actual_ranges['Parkinson']
qlike_pk = {}
for model_name in all_models:
    fcast = forecasts[model_name]
    valid = np.isfinite(fcast) & np.isfinite(actual_pk) & (fcast > 0) & (actual_pk > 0)
    q = qlike(actual_pk[valid], fcast[valid])
    qlike_pk[model_name] = q
    print(f"    {model_name:18s}: QLIKE={q:.6f}")

# --- Key comparison: K934 Parkinson CARR vs Gap-Adjusted variants ---
print("\n  === KEY COMPARISON: Gap-Adjusted vs Parkinson ===")
pk_qlike = qlike_r2['CARR_Parkinson']
for est_name in ['GK', 'RS', 'YZ']:
    model_name = f'CARR_{est_name}'
    adj_qlike = qlike_r2[model_name]
    improvement = (pk_qlike - adj_qlike) / pk_qlike * 100
    print(f"    {model_name:18s}: QLIKE={adj_qlike:.6f} "
          f"({'improved' if improvement > 0 else 'worse'} by {abs(improvement):.2f}% vs Parkinson)")

# ============================================================
# 7. VISUALIZATION & SAVE
# ============================================================
print("\n[7/7] Creating visualization and saving results...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K935: Gap-Adjusted CARR — Range Estimator Comparison\n'
             'SPY OOS 2016-2026, Patton (2011) QLIKE on r²', fontsize=13, fontweight='bold')

# Plot 1: QLIKE on r² bar chart
ax = axes[0, 0]
models_sorted = [m for m, _ in ranking]
qlike_vals = [qlike_r2[m] for m in models_sorted]
colors = ['#e74c3c' if 'Parkinson' in m else '#3498db' if 'CARR' in m else '#2ecc71' for m in models_sorted]
bars = ax.barh(range(len(models_sorted)), qlike_vals, color=colors, edgecolor='white', linewidth=0.5)
ax.set_yticks(range(len(models_sorted)))
ax.set_yticklabels(models_sorted, fontsize=9)
ax.set_xlabel('QLIKE on r² (lower = better)')
ax.set_title('QLIKE on r² Ranking')
ax.invert_yaxis()
for bar, val in zip(bars, qlike_vals):
    ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
            f'{val:.4f}', va='center', fontsize=8)

# Plot 2: Spearman rho bar chart
ax = axes[0, 1]
spearman_sorted = sorted(spearman_results.items(), key=lambda x: x[1]['rho'], reverse=True)
models_sp = [m for m, _ in spearman_sorted]
rho_vals = [v['rho'] for _, v in spearman_sorted]
colors_sp = ['#e74c3c' if 'Parkinson' in m else '#3498db' if 'CARR' in m else '#2ecc71' for m in models_sp]
bars = ax.barh(range(len(models_sp)), rho_vals, color=colors_sp, edgecolor='white', linewidth=0.5)
ax.set_yticks(range(len(models_sp)))
ax.set_yticklabels(models_sp, fontsize=9)
ax.set_xlabel('Spearman rho (higher = better)')
ax.set_title('Spearman Rank Correlation with r²')
ax.invert_yaxis()
for bar, val in zip(bars, rho_vals):
    ax.text(bar.get_width() + 0.005, bar.get_y() + bar.get_height()/2,
            f'{val:.4f}', va='center', fontsize=8)

# Plot 3: Time series of forecasts (200-day window)
ax = axes[1, 0]
# Show a representative window
window_start = 500
window_end = 700
t_range = range(window_start, window_end)
ax.plot(t_range, actual_r2[window_start:window_end], 'k-', alpha=0.3, linewidth=0.5, label='Actual r²')
for model_name in ['CARR_Parkinson', 'CARR_YZ', 'GARCH', 'MF_GJR']:
    fcast = forecasts[model_name]
    style = '-' if 'GARCH' in model_name or 'MF_GJR' in model_name else '--'
    ax.plot(t_range, fcast[window_start:window_end], style, linewidth=1.0, alpha=0.8, label=model_name)
ax.set_xlabel('OOS day index')
ax.set_ylabel('Variance forecast')
ax.set_title('Forecast Comparison (sample window)')
ax.legend(fontsize=7, loc='upper right')
ax.set_ylim(bottom=0)

# Plot 4: Cumulative QLIKE difference (CARR_YZ - CARR_Parkinson)
ax = axes[1, 1]
# Compare each gap-adjusted CARR vs Parkinson
for est_name, color, ls in [('GK', '#2980b9', '-'), ('RS', '#27ae60', '--'), ('YZ', '#8e44ad', '-.')]:
    f_pk = forecasts['CARR_Parkinson']
    f_adj = forecasts[f'CARR_{est_name}']
    valid = (np.isfinite(f_pk) & np.isfinite(f_adj) & np.isfinite(actual_r2)
             & (f_pk > 0) & (f_adj > 0) & (actual_r2 > 0))
    loss_pk = qlike_pointwise(actual_r2[valid], f_pk[valid])
    loss_adj = qlike_pointwise(actual_r2[valid], f_adj[valid])
    cum_diff = np.cumsum(loss_pk - loss_adj)  # positive = Parkinson worse
    ax.plot(cum_diff, color=color, linestyle=ls, linewidth=1.0, label=f'{est_name} - Parkinson')

ax.axhline(y=0, color='gray', linestyle=':', linewidth=0.5)
ax.set_xlabel('OOS day index')
ax.set_ylabel('Cumulative QLIKE difference')
ax.set_title('Cumulative QLIKE: Parkinson - Gap-Adjusted\n(positive = gap-adjusted better)')
ax.legend(fontsize=8)

plt.tight_layout()
chart_path = os.path.join(os.path.dirname(__file__), 'k935_comparison.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved: {chart_path}")

# --- Save results ---
# First-fit parameters
first_fit_params = {}
for model_name in all_models:
    if model_name in model_params:
        p = model_params[model_name]
        first_fit_params[model_name] = {k: round(v, 8) if isinstance(v, float) else v
                                         for k, v in p.items()}

results = {
    "experiment_id": "K935",
    "title": "Gap-Adjusted CARR — Fixing Parkinson Overnight Bias",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY + ^VIX)",
    "period": "2004-01-01 ~ 2025-12-31",
    "oos_period": f"{oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}",
    "oos_days": n_oos,
    "window": WINDOW,
    "refit_every": REFIT,
    "n_refits": n_refits,
    "references": [
        "Parkinson (1980) 'The Extreme Value Method for Estimating the Variance of the Rate of Return'",
        "Garman & Klass (1980) 'On the Estimation of Security Price Volatilities from Historical Data'",
        "Rogers & Satchell (1991) 'Estimating Variance from High, Low and Closing Prices'",
        "Yang & Zhang (2000) 'Drift Independent Volatility Estimation'",
        "Chou (2005) 'Forecasting Financial Volatilities with Extreme Values'",
        "Patton (2011) J. Econometrics 160"
    ],
    "range_estimator_stats": {
        "negative_values": {"GK": int(n_neg_gk), "RS": int(n_neg_rs), "YZ": int(n_neg_yz)},
        "correlations_with_r2": {
            est_name: round(float(corr_matrix.loc[col, 'r2']), 4)
            for est_name, col in ESTIMATORS.items()
        },
        "means": {
            est_name: round(float(spy[col].mean()), 8)
            for est_name, col in ESTIMATORS.items()
        }
    },
    "model_parameters_first_fit": first_fit_params,
    "layer1_native_target_qlike": {k: round(v, 6) for k, v in native_qlike.items()},
    "layer2_qlike_on_r2_patton": {k: round(v, 6) for k, v in qlike_r2.items()},
    "layer2_ranking": [
        {"rank": i+1, "model": m, "qlike": round(q, 6)}
        for i, (m, q) in enumerate(ranking)
    ],
    "layer3_spearman": spearman_results,
    "layer4_dm_tests": dm_results,
    "supplementary_qlike_on_parkinson_var": {k: round(v, 6) for k, v in qlike_pk.items()},
    "key_comparison_vs_parkinson_carr": {
        est_name: {
            "qlike_r2": round(qlike_r2[f'CARR_{est_name}'], 6),
            "improvement_pct": round((qlike_r2['CARR_Parkinson'] - qlike_r2[f'CARR_{est_name}'])
                                     / qlike_r2['CARR_Parkinson'] * 100, 2),
            "spearman_rho": spearman_results[f'CARR_{est_name}']['rho']
        }
        for est_name in ['GK', 'RS', 'YZ']
    },
    "conclusions": {
        "H1_gap_adjusted_better_than_parkinson": None,  # Will be filled after results
        "H2_approaches_garch_calibration": None,
        "best_carr_variant": None,
        "overall_best": None,
    }
}

# Fill in conclusions based on actual results
best_carr = min([(m, q) for m, q in qlike_r2.items() if 'CARR' in m], key=lambda x: x[1])
garch_qlike = qlike_r2['GARCH']
pk_qlike_val = qlike_r2['CARR_Parkinson']

# H1: Any gap-adjusted CARR better than Parkinson?
gap_adjusted_better = any(qlike_r2[f'CARR_{e}'] < pk_qlike_val for e in ['GK', 'RS', 'YZ'])
results["conclusions"]["H1_gap_adjusted_better_than_parkinson"] = gap_adjusted_better

# H2: Best CARR vs GARCH
best_carr_qlike = best_carr[1]
gap_to_garch = (best_carr_qlike - garch_qlike) / garch_qlike * 100
results["conclusions"]["H2_approaches_garch_calibration"] = f"{gap_to_garch:+.2f}% gap to GARCH"
results["conclusions"]["best_carr_variant"] = best_carr[0]
results["conclusions"]["overall_best"] = ranking[0][0]

results_path = os.path.join(os.path.dirname(__file__), 'k935_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"  Results saved: {results_path}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Best CARR variant: {best_carr[0]} (QLIKE on r² = {best_carr[1]:.6f})")
print(f"  Parkinson CARR:    QLIKE on r² = {pk_qlike_val:.6f}")
print(f"  GARCH(1,1):        QLIKE on r² = {garch_qlike:.6f}")
print(f"  MF-GJR(VIX):       QLIKE on r² = {qlike_r2['MF_GJR']:.6f}")
print(f"\n  H1 (gap-adjusted < Parkinson): {gap_adjusted_better}")
print(f"  H2 (best CARR gap to GARCH):   {gap_to_garch:+.2f}%")
print(f"\n  Spearman ranking:")
for m, v in spearman_sorted:
    print(f"    {m:18s}: rho={v['rho']:.4f}")
print("\nDone.")
