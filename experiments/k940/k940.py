"""
K940: Simple Neural Network Volatility Predictor
Can ML models (MLP, Random Forest, Ridge) beat MF-GJR(VIX) for daily vol prediction?

Background:
  K889: MF-GJR(VIX) best model QLIKE≈1.47, DM t=-4.42 vs GARCH
  K937: 4 ensemble methods all fail to beat MF-GJR(VIX) (H3 confirmed)
  K482: Equal weight ensemble best (combination puzzle)
  No ML model has been tested before -- this is the first attempt

Hypotheses:
  H1: MLP captures nonlinearities missed by MF-GJR → beats in QLIKE
  H2: MLP ≈ MF-GJR → MF structure already sufficient
  H3: MLP < GARCH → overfitting (daily vol signal-to-noise too low)

Features (ALL lagged, using t-1..t-k info to predict t):
  1. σ²_GARCH_{t-1} (GARCH(1,1) fitted variance)
  2. log(VIX_{t-1})
  3. r²_{t-1} (previous day squared return)
  4. |r_{t-1}| (previous day absolute return)
  5. YZ_{t-1} (Yang-Zhang variance)
  6. r²_{t-2}..r²_{t-5} (squared returns lag 2-5)
  7. σ²_GARCH_{t-1} / VIX²_{t-1} (GARCH-VIX ratio)
  8. 20-day rolling σ² (using data up to t-1)

ML Models:
  1. MLP Regressor (2 layers: 32, 16)
  2. Ridge Regression (linear baseline)
  3. Random Forest (nonlinear baseline)

Benchmark Models:
  1. GARCH(1,1)
  2. GJR(1,1,1)
  3. MF-GJR(VIX)

Evaluation:
  - QLIKE on r² (Patton 2011 proxy-robust)
  - MSE on r²
  - Spearman ρ
  - DM test (Harvey |t| > 3.0)

Training protocol:
  - Expanding window, retrain every 63 trading days
  - Rolling z-score standardization (train window only)
  - OOS: 2016-01-01 ~ 2025-12-31

References:
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies"
  Bucci (2020) "Realized Volatility Forecasting with Neural Networks"
  Risse (2019) "Combining Wavelet Decomposition with Machine Learning..."
  Harvey et al. (2016) "Tests for Forecast Encompassing"
  Christensen et al. (2023) "A Machine Learning Approach to Volatility Forecasting"

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2004-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000 (expanding), Refit: every 63 trading days
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
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K940: Simple Neural Network Volatility Predictor")
print("=" * 60)

print("\n[1/7] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-01-01', progress=False, auto_adjust=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-01-01', progress=False, auto_adjust=False)

# Flatten multi-level columns if needed (yfinance returns MultiIndex with ticker)
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
spy['abs_r'] = np.abs(spy['log_return'])

# Yang-Zhang range estimator
spy['overnight_return'] = spy['log_O'] - spy['log_C'].shift(1)
spy['overnight_sq'] = spy['overnight_return'] ** 2
spy['range_rs'] = ((spy['log_H'] - spy['log_C']) * (spy['log_H'] - spy['log_O'])
                  + (spy['log_L'] - spy['log_C']) * (spy['log_L'] - spy['log_O']))
k_yz = 0.34 / (1.34 + 2.0)
spy['open_var'] = ((spy['log_H'] - spy['log_O'])**2 + (spy['log_L'] - spy['log_O'])**2)
spy['range_yz'] = spy['overnight_sq'] + k_yz * spy['open_var'] + (1 - k_yz) * spy['range_rs']

# Add VIX
vix_close = vix['Close'].rename('VIX')
spy = spy.join(vix_close, how='left')
spy['VIX'] = spy['VIX'].ffill()
spy['log_VIX'] = np.log(spy['VIX'])

# 20-day rolling variance (using r², NOT forward-looking)
spy['rolling_var_20'] = spy['r2'].rolling(window=20, min_periods=20).mean()

# Lagged squared returns (r²_{t-2} to r²_{t-5})
for lag in range(2, 6):
    spy[f'r2_lag{lag}'] = spy['r2'].shift(lag)

# Drop NaN
spy = spy.dropna(subset=['range_yz', 'log_return', 'r2', 'VIX', 'overnight_return',
                          'rolling_var_20', 'r2_lag5'])
# Floor range
FLOOR = 1e-10
spy['range_yz'] = np.maximum(spy['range_yz'], FLOOR)

print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Descriptive stats
print("\n  Descriptive Statistics:")
for name, col in [('r²', 'r2'), ('|r|', 'abs_r'), ('YZ Range', 'range_yz'), ('VIX', 'VIX')]:
    vals = spy[col]
    print(f"    {name:12s}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
          f"skew={vals.skew():.3f}, kurt={vals.kurtosis():.3f}")


# ============================================================
# 2. GARCH/GJR/MF-GJR MODEL IMPLEMENTATIONS
# ============================================================
print("\n[2/7] Benchmark model implementations...")


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


def garch_variance_path(params, returns):
    """Compute full conditional variance path for GARCH."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    h = np.zeros(T)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
        if h[t] <= 1e-10:
            h[t] = 1e-10
    return h


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


def gjr_variance_path(params, returns):
    """Compute full conditional variance path for GJR."""
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    h = np.zeros(T)
    h[0] = omega / max(1 - alpha - 0.5*gamma - beta, 0.01)
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * (r[t-1] < 0) + beta * h[t-1]
        if h[t] <= 1e-10:
            h[t] = 1e-10
    return h


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


def mf_gjr_variance_path(params, returns, log_vix):
    """Compute full conditional variance path for MF-GJR(VIX)."""
    theta0, theta1 = params['theta0'], params['theta1']
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    lv = np.asarray(log_vix, dtype=np.float64)

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
    return h


# ============================================================
# 3. ROLLING OOS WITH EXPANDING WINDOW
# ============================================================
print("\n[3/7] Rolling OOS estimation (expanding window, refit every 63 days)...")

WINDOW_MIN = 2000  # Minimum training window
REFIT_EVERY = 63   # Refit every quarter
OOS_START = '2016-01-01'

# Find OOS start index
oos_mask = spy.index >= OOS_START
oos_start_idx = spy.index.get_loc(spy.index[oos_mask][0])
print(f"  Min window: {WINDOW_MIN}, Refit every: {REFIT_EVERY}")
print(f"  OOS start: {spy.index[oos_mask][0].strftime('%Y-%m-%d')} (idx={oos_start_idx})")
print(f"  OOS days: {oos_mask.sum()}")

returns_arr = spy['log_return'].values
r2_arr = spy['r2'].values
abs_r_arr = spy['abs_r'].values
range_yz_arr = spy['range_yz'].values
log_vix_arr = spy['log_VIX'].values
rolling_var_arr = spy['rolling_var_20'].values

n_total = len(spy)
n_oos = oos_mask.sum()

# Storage for OOS forecasts
fc_garch = np.full(n_total, np.nan)
fc_gjr = np.full(n_total, np.nan)
fc_mfgjr = np.full(n_total, np.nan)
fc_mlp = np.full(n_total, np.nan)
fc_ridge = np.full(n_total, np.nan)
fc_rf = np.full(n_total, np.nan)

# GARCH/GJR/MF-GJR params
params_garch = None
params_gjr = None
params_mfgjr = None

# ML models
model_mlp = None
model_ridge = None
model_rf = None
feature_mean = None
feature_std = None

refit_counter = 0
n_refits = 0

# Build feature matrix columns
# Features: [garch_var, log_vix, r2_lag1, abs_r_lag1, yz_lag1, r2_lag2..5, garch_vix_ratio, rolling_var]
FEATURE_NAMES = ['garch_var', 'log_vix', 'r2_lag1', 'abs_r_lag1', 'yz_lag1',
                 'r2_lag2', 'r2_lag3', 'r2_lag4', 'r2_lag5',
                 'garch_vix_ratio', 'rolling_var_20']

print("\n  Starting rolling OOS estimation...")

for t in range(oos_start_idx, n_total):
    # Refit all models
    if params_garch is None or refit_counter >= REFIT_EVERY:
        train_end = t  # exclusive
        train_start = 0  # expanding window (always from start)

        train_ret = returns_arr[train_start:train_end]
        train_lvix = log_vix_arr[train_start:train_end]

        # Fit GARCH family
        params_garch = garch_fit(train_ret)
        params_gjr = gjr_fit(train_ret)
        params_mfgjr = mf_gjr_fit(train_ret, train_lvix)

        # Build GARCH variance path for the training period
        garch_var_path = garch_variance_path(params_garch, train_ret)

        # Build feature matrix for training
        # All features are lagged: feature at time t uses info up to t-1
        T_train = len(train_ret)
        X_train_list = []
        y_train_list = []

        # Need at least 20+5 = 25 warm-up days for rolling_var and lag5
        warmup = max(25, 1)

        for i in range(warmup, T_train):
            # Features at time i use info up to i-1
            feat = np.array([
                garch_var_path[i],           # GARCH variance at i (uses info up to i-1 via recursion)
                log_vix_arr[train_start + i - 1],  # log VIX at i-1
                r2_arr[train_start + i - 1],       # r² at i-1
                abs_r_arr[train_start + i - 1],    # |r| at i-1
                range_yz_arr[train_start + i - 1], # YZ at i-1
                r2_arr[train_start + i - 2],       # r² at i-2
                r2_arr[train_start + i - 3],       # r² at i-3
                r2_arr[train_start + i - 4],       # r² at i-4
                r2_arr[train_start + i - 5],       # r² at i-5
                garch_var_path[i] / max((spy['VIX'].iloc[train_start + i - 1] / 100)**2 / 252, 1e-10),  # GARCH/VIX² ratio
                rolling_var_arr[train_start + i - 1],  # 20-day rolling var at i-1
            ])
            X_train_list.append(feat)
            y_train_list.append(r2_arr[train_start + i])  # Target: r² at i

        X_train = np.array(X_train_list)
        y_train = np.array(y_train_list)

        # Standardize features (using training data only, NO lookahead)
        feature_mean = X_train.mean(axis=0)
        feature_std = X_train.std(axis=0)
        feature_std[feature_std < 1e-10] = 1.0  # prevent division by zero
        X_train_scaled = (X_train - feature_mean) / feature_std

        # Fit ML models
        model_mlp = MLPRegressor(
            hidden_layer_sizes=(32, 16),
            activation='relu',
            solver='adam',
            max_iter=500,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1,
            n_iter_no_change=20,
            learning_rate='adaptive',
            learning_rate_init=0.001,
        )
        model_mlp.fit(X_train_scaled, y_train)

        model_ridge = Ridge(alpha=1.0)
        model_ridge.fit(X_train_scaled, y_train)

        model_rf = RandomForestRegressor(
            n_estimators=100,
            max_depth=5,
            random_state=42,
            n_jobs=-1,
        )
        model_rf.fit(X_train_scaled, y_train)

        refit_counter = 0
        n_refits += 1

        if n_refits <= 3 or n_refits % 10 == 0:
            print(f"    Refit #{n_refits} at t={t} ({spy.index[t].strftime('%Y-%m-%d')})"
                  f" GARCH pers={params_garch['persistence']:.4f}"
                  f" MF-GJR pers={params_mfgjr['persistence']:.4f}"
                  f" Train samples={len(y_train)}")

    refit_counter += 1

    # === Compute forecasts for day t ===

    # GARCH: build variance path from train start to t-1, forecast for t
    full_ret = returns_arr[0:t]
    garch_h = garch_variance_path(params_garch, full_ret)
    # Forecast for t: h[t] = omega + alpha * r²[t-1] + beta * h[t-1]
    omega_g, alpha_g, beta_g = params_garch['omega'], params_garch['alpha'], params_garch['beta']
    fc_garch[t] = omega_g + alpha_g * returns_arr[t-1]**2 + beta_g * garch_h[-1]
    fc_garch[t] = max(fc_garch[t], 1e-10)

    # GJR: build variance path from train start to t-1, forecast for t
    gjr_h = gjr_variance_path(params_gjr, full_ret)
    omega_j, alpha_j, gamma_j, beta_j = params_gjr['omega'], params_gjr['alpha'], params_gjr['gamma'], params_gjr['beta']
    fc_gjr[t] = omega_j + alpha_j * returns_arr[t-1]**2 + gamma_j * returns_arr[t-1]**2 * (returns_arr[t-1] < 0) + beta_j * gjr_h[-1]
    fc_gjr[t] = max(fc_gjr[t], 1e-10)

    # MF-GJR: build variance path, forecast for t
    mfgjr_h_path = mf_gjr_variance_path(params_mfgjr, full_ret, log_vix_arr[0:t])
    theta0, theta1 = params_mfgjr['theta0'], params_mfgjr['theta1']
    omega_m, alpha_m, gamma_m, beta_m = params_mfgjr['omega'], params_mfgjr['alpha'], params_mfgjr['gamma'], params_mfgjr['beta']
    # tau at t uses VIX at t-1 (last known)
    tau_t = np.exp(theta0 + theta1 * log_vix_arr[t-1])
    tau_t = max(tau_t, 1e-16)
    # g at t: need g[t-1] and shock from t-1
    tau_tm1 = np.exp(theta0 + theta1 * log_vix_arr[t-1])
    tau_tm1 = max(tau_tm1, 1e-16)
    # Reconstruct g path
    g_path = mfgjr_h_path / np.exp(theta0 + theta1 * log_vix_arr[0:t])
    g_path = np.maximum(g_path, 1e-10)
    shock_tm1 = returns_arr[t-1]**2 / tau_tm1
    asym_tm1 = shock_tm1 * (returns_arr[t-1] < 0)
    g_t = omega_m + alpha_m * shock_tm1 + gamma_m * asym_tm1 + beta_m * g_path[-1]
    g_t = max(g_t, 1e-10)
    fc_mfgjr[t] = tau_t * g_t
    fc_mfgjr[t] = max(fc_mfgjr[t], 1e-10)

    # === ML Models ===
    # Build feature vector for predicting day t (using info up to t-1)
    garch_var_at_t = fc_garch[t]  # GARCH conditional var forecast for t
    vix_squared_daily = (spy['VIX'].iloc[t-1] / 100)**2 / 252  # annualized VIX to daily

    feat_t = np.array([
        garch_var_at_t,
        log_vix_arr[t-1],
        r2_arr[t-1],
        abs_r_arr[t-1],
        range_yz_arr[t-1],
        r2_arr[t-2],
        r2_arr[t-3],
        r2_arr[t-4],
        r2_arr[t-5],
        garch_var_at_t / max(vix_squared_daily, 1e-10),
        rolling_var_arr[t-1],
    ]).reshape(1, -1)

    # Standardize using training statistics (NO lookahead)
    feat_t_scaled = (feat_t - feature_mean) / feature_std

    # Predict
    fc_mlp[t] = max(model_mlp.predict(feat_t_scaled)[0], 1e-10)
    fc_ridge[t] = max(model_ridge.predict(feat_t_scaled)[0], 1e-10)
    fc_rf[t] = max(model_rf.predict(feat_t_scaled)[0], 1e-10)

print(f"\n  Total refits: {n_refits}")
print(f"  OOS forecasts generated: {np.sum(~np.isnan(fc_garch[oos_start_idx:]))}")


# ============================================================
# 4. EVALUATION
# ============================================================
print("\n[4/7] Evaluation...")

# Extract OOS data
oos_idx = spy.index >= OOS_START
r2_oos = r2_arr[oos_idx]
dates_oos = spy.index[oos_idx]

forecasts = {
    'GARCH(1,1)': fc_garch[oos_idx],
    'GJR(1,1,1)': fc_gjr[oos_idx],
    'MF-GJR(VIX)': fc_mfgjr[oos_idx],
    'Ridge': fc_ridge[oos_idx],
    'Random Forest': fc_rf[oos_idx],
    'MLP': fc_mlp[oos_idx],
}

# Sanity check: no NaN
for name, fc in forecasts.items():
    nan_count = np.sum(np.isnan(fc))
    if nan_count > 0:
        print(f"  WARNING: {name} has {nan_count} NaN forecasts!")

# QLIKE on r²
print("\n  QLIKE on r² (lower is better):")
qlike_results = {}
for name, fc in forecasts.items():
    valid = ~np.isnan(fc) & ~np.isnan(r2_oos)
    if valid.sum() > 0:
        q = qlike(r2_oos[valid], fc[valid])
        qlike_results[name] = q
        print(f"    {name:20s}: QLIKE = {q:.4f}")

# MSE on r²
print("\n  MSE on r² (lower is better):")
mse_results = {}
for name, fc in forecasts.items():
    valid = ~np.isnan(fc) & ~np.isnan(r2_oos)
    if valid.sum() > 0:
        mse = np.mean((r2_oos[valid] - fc[valid])**2)
        mse_results[name] = mse
        print(f"    {name:20s}: MSE = {mse:.4e}")

# Spearman rank correlation
print("\n  Spearman ρ (higher is better):")
spearman_results = {}
for name, fc in forecasts.items():
    valid = ~np.isnan(fc) & ~np.isnan(r2_oos)
    if valid.sum() > 0:
        rho, pval = stats.spearmanr(r2_oos[valid], fc[valid])
        spearman_results[name] = rho
        print(f"    {name:20s}: ρ = {rho:.4f} (p={pval:.2e})")


# ============================================================
# 5. DM TESTS
# ============================================================
print("\n[5/7] DM Tests (Harvey |t| > 3.0)...")

# Compute QLIKE pointwise losses
losses = {}
for name, fc in forecasts.items():
    valid = ~np.isnan(fc) & ~np.isnan(r2_oos)
    losses[name] = qlike_pointwise(r2_oos[valid], fc[valid])

# DM test: each model vs MF-GJR(VIX)
benchmark = 'MF-GJR(VIX)'
print(f"\n  DM test vs {benchmark} (negative t = model better than benchmark):")
dm_results = {}
for name in forecasts.keys():
    if name == benchmark:
        continue
    try:
        t_stat, p_val = dm_test(losses[benchmark], losses[name])
        dm_results[name] = {'t_stat': t_stat, 'p_val': p_val}
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.96 else ""))
        direction = "BETTER" if t_stat > 0 else "WORSE"
        print(f"    {name:20s} vs {benchmark}: t={t_stat:+.3f}, p={p_val:.4f} {sig} ({direction})")
    except Exception as e:
        print(f"    {name:20s}: DM test failed: {e}")
        dm_results[name] = {'t_stat': np.nan, 'p_val': np.nan}

# Also test MLP vs Ridge and MLP vs RF
print(f"\n  DM test among ML models:")
for pair in [('MLP', 'Ridge'), ('MLP', 'Random Forest'), ('Ridge', 'Random Forest')]:
    try:
        t_stat, p_val = dm_test(losses[pair[1]], losses[pair[0]])
        sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else "")
        print(f"    {pair[0]:15s} vs {pair[1]:15s}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")
    except Exception as e:
        print(f"    {pair[0]:15s} vs {pair[1]:15s}: DM test failed: {e}")


# ============================================================
# 6. FEATURE IMPORTANCE (Random Forest)
# ============================================================
print("\n[6/7] Feature importance (last RF model)...")

rf_importances = model_rf.feature_importances_
sorted_idx = np.argsort(rf_importances)[::-1]

print("\n  Random Forest Feature Importance:")
for rank, idx in enumerate(sorted_idx):
    print(f"    {rank+1}. {FEATURE_NAMES[idx]:20s}: {rf_importances[idx]:.4f}")

# Ridge coefficients
ridge_coefs = model_ridge.coef_
ridge_sorted = np.argsort(np.abs(ridge_coefs))[::-1]
print("\n  Ridge Regression Coefficients (absolute, standardized):")
for rank, idx in enumerate(ridge_sorted):
    print(f"    {rank+1}. {FEATURE_NAMES[idx]:20s}: {ridge_coefs[idx]:+.6f}")


# ============================================================
# 7. CHARTS & RESULTS
# ============================================================
print("\n[7/7] Generating charts and saving results...")

# Chart 1: Model Comparison Bar Chart
fig, axes = plt.subplots(1, 3, figsize=(16, 5))
fig.suptitle('K940: ML vs Traditional Vol Models — OOS Comparison', fontsize=14, fontweight='bold')

# QLIKE bars
model_names = list(qlike_results.keys())
qlike_vals = [qlike_results[n] for n in model_names]
colors = ['#2196F3', '#2196F3', '#FF5722', '#4CAF50', '#4CAF50', '#4CAF50']
# Color coding: blue=traditional, red=MF-GJR (benchmark), green=ML
color_map = {'GARCH(1,1)': '#2196F3', 'GJR(1,1,1)': '#2196F3',
             'MF-GJR(VIX)': '#FF5722',
             'Ridge': '#4CAF50', 'Random Forest': '#4CAF50', 'MLP': '#4CAF50'}
bar_colors = [color_map.get(n, '#999') for n in model_names]

axes[0].barh(model_names, qlike_vals, color=bar_colors, edgecolor='white')
axes[0].set_xlabel('QLIKE (lower = better)')
axes[0].set_title('QLIKE on r²')
axes[0].axvline(x=qlike_results.get('MF-GJR(VIX)', 0), color='red', linestyle='--', alpha=0.5, label='MF-GJR')
axes[0].invert_yaxis()

# MSE bars
mse_vals = [mse_results[n] for n in model_names]
axes[1].barh(model_names, mse_vals, color=bar_colors, edgecolor='white')
axes[1].set_xlabel('MSE (lower = better)')
axes[1].set_title('MSE on r²')
axes[1].axvline(x=mse_results.get('MF-GJR(VIX)', 0), color='red', linestyle='--', alpha=0.5)
axes[1].invert_yaxis()

# Spearman bars
spearman_vals = [spearman_results[n] for n in model_names]
axes[2].barh(model_names, spearman_vals, color=bar_colors, edgecolor='white')
axes[2].set_xlabel('Spearman ρ (higher = better)')
axes[2].set_title('Spearman Rank Correlation')
axes[2].axvline(x=spearman_results.get('MF-GJR(VIX)', 0), color='red', linestyle='--', alpha=0.5)
axes[2].invert_yaxis()

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k940_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k940_comparison.png")


# Chart 2: Feature Importance
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
fig.suptitle('K940: Feature Importance Analysis', fontsize=14, fontweight='bold')

# RF importance
rf_sorted_names = [FEATURE_NAMES[i] for i in sorted_idx]
rf_sorted_vals = [rf_importances[i] for i in sorted_idx]
axes[0].barh(rf_sorted_names, rf_sorted_vals, color='#4CAF50', edgecolor='white')
axes[0].set_xlabel('Importance')
axes[0].set_title('Random Forest Feature Importance')
axes[0].invert_yaxis()

# Ridge coefficients (absolute)
ridge_names = [FEATURE_NAMES[i] for i in ridge_sorted]
ridge_vals = [ridge_coefs[i] for i in ridge_sorted]
colors_ridge = ['#4CAF50' if v > 0 else '#FF5722' for v in ridge_vals]
axes[1].barh(ridge_names, ridge_vals, color=colors_ridge, edgecolor='white')
axes[1].set_xlabel('Coefficient (standardized)')
axes[1].set_title('Ridge Regression Coefficients')
axes[1].axvline(x=0, color='black', linewidth=0.5)
axes[1].invert_yaxis()

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k940_feature_importance.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k940_feature_importance.png")


# Chart 3: Rolling QLIKE comparison (252-day rolling)
fig, ax = plt.subplots(figsize=(14, 5))
rolling_window = 252

for name in ['GARCH(1,1)', 'MF-GJR(VIX)', 'MLP', 'Random Forest']:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & ~np.isnan(r2_oos)
    pw_loss = np.full(len(r2_oos), np.nan)
    for i in range(len(r2_oos)):
        if valid[i]:
            pw_loss[i] = r2_oos[i] / fc[i] - np.log(r2_oos[i] / fc[i]) - 1

    rolling_q = pd.Series(pw_loss, index=dates_oos).rolling(rolling_window).mean()
    ax.plot(rolling_q.index, rolling_q.values, label=name, alpha=0.8)

ax.set_title('K940: 252-Day Rolling QLIKE', fontweight='bold')
ax.set_ylabel('QLIKE (lower = better)')
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k940_rolling_qlike.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k940_rolling_qlike.png")


# Save results JSON
results = {
    'experiment_id': 'K940',
    'title': 'Simple Neural Network Volatility Predictor',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY + ^VIX)',
    'period': '2004-01-01 ~ 2025-12-31',
    'oos_period': f"{dates_oos[0].strftime('%Y-%m-%d')} ~ {dates_oos[-1].strftime('%Y-%m-%d')}",
    'n_oos': int(n_oos),
    'n_refits': n_refits,
    'refit_every': REFIT_EVERY,
    'window_type': 'expanding (from 2004)',
    'seed': 42,
    'models': {
        'traditional': ['GARCH(1,1)', 'GJR(1,1,1)', 'MF-GJR(VIX)'],
        'ml': ['Ridge', 'Random Forest', 'MLP'],
    },
    'features': FEATURE_NAMES,
    'ml_config': {
        'MLP': {'hidden_layers': [32, 16], 'activation': 'relu', 'solver': 'adam',
                'max_iter': 500, 'early_stopping': True, 'validation_fraction': 0.1},
        'Ridge': {'alpha': 1.0},
        'Random Forest': {'n_estimators': 100, 'max_depth': 5},
    },
    'results': {
        'qlike': {k: round(v, 4) for k, v in qlike_results.items()},
        'mse': {k: float(f"{v:.6e}") for k, v in mse_results.items()},
        'spearman': {k: round(v, 4) for k, v in spearman_results.items()},
    },
    'dm_tests_vs_mfgjr': {
        name: {
            't_stat': round(v['t_stat'], 3) if not np.isnan(v['t_stat']) else None,
            'p_val': round(v['p_val'], 4) if not np.isnan(v['p_val']) else None,
            'significant_harvey': abs(v['t_stat']) > 3.0 if not np.isnan(v['t_stat']) else False,
        }
        for name, v in dm_results.items()
    },
    'feature_importance_rf': {
        FEATURE_NAMES[i]: round(float(rf_importances[i]), 4) for i in sorted_idx
    },
    'ridge_coefficients': {
        FEATURE_NAMES[i]: round(float(ridge_coefs[i]), 6) for i in ridge_sorted
    },
    'conclusion': '',  # Will be filled after analysis
    'references': [
        'Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies", JoE',
        'Bucci (2020) "Realized Volatility Forecasting with Neural Networks", JFEC',
        'Risse (2019) "Combining Wavelet Decomposition with Machine Learning...", JFEC',
        'Harvey et al. (2016) "Tests for Forecast Encompassing", JoE',
        'Christensen et al. (2023) "A Machine Learning Approach to Volatility Forecasting", JBF',
    ],
}

# Determine conclusion
best_model = min(qlike_results, key=qlike_results.get)
mfgjr_qlike = qlike_results.get('MF-GJR(VIX)', None)
best_ml_qlike = min(qlike_results[k] for k in ['Ridge', 'Random Forest', 'MLP'] if k in qlike_results)
best_ml_name = min(['Ridge', 'Random Forest', 'MLP'], key=lambda k: qlike_results.get(k, float('inf')))

if best_model == 'MF-GJR(VIX)':
    conclusion = (f"H2 confirmed: No ML model beats MF-GJR(VIX). "
                  f"Best ML ({best_ml_name}) QLIKE={best_ml_qlike:.4f} vs MF-GJR QLIKE={mfgjr_qlike:.4f}. "
                  f"The MF structure with VIX already captures the relevant nonlinearities.")
elif best_model in ['MLP', 'Ridge', 'Random Forest']:
    # Check DM significance
    dm_info = dm_results.get(best_model, {})
    t_stat_val = dm_info.get('t_stat', 0)
    if abs(t_stat_val) > 3.0 and t_stat_val > 0:
        conclusion = (f"H1 partially supported: {best_model} QLIKE={qlike_results[best_model]:.4f} "
                      f"vs MF-GJR QLIKE={mfgjr_qlike:.4f} (DM t={t_stat_val:.3f}). "
                      f"ML captures additional nonlinearities beyond MF structure.")
    else:
        conclusion = (f"H2 confirmed: {best_model} marginally better QLIKE={qlike_results[best_model]:.4f} "
                      f"vs MF-GJR QLIKE={mfgjr_qlike:.4f}, but NOT significant (DM |t|<3.0). "
                      f"MF-GJR(VIX) remains effectively best.")
else:
    conclusion = f"Unexpected: best model is {best_model} with QLIKE={qlike_results[best_model]:.4f}"

# Check for GARCH-beating
garch_qlike = qlike_results.get('GARCH(1,1)', None)
ml_vs_garch = all(qlike_results.get(m, float('inf')) < garch_qlike for m in ['MLP', 'Ridge', 'Random Forest'])
if not ml_vs_garch:
    conclusion += " CAUTION: Some ML models worse than GARCH — possible overfitting on daily data."

results['conclusion'] = conclusion
print(f"\n  Conclusion: {conclusion}")

# Save JSON
results_path = os.path.join(SCRIPT_DIR, 'k940_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"  Saved {results_path}")


# ============================================================
# SUMMARY TABLE
# ============================================================
print("\n" + "=" * 80)
print("K940 SUMMARY: ML vs Traditional Volatility Models")
print("=" * 80)
print(f"{'Model':20s} {'QLIKE':>10s} {'MSE':>12s} {'Spearman':>10s} {'DM vs MF-GJR':>15s}")
print("-" * 70)

for name in ['GARCH(1,1)', 'GJR(1,1,1)', 'MF-GJR(VIX)', 'Ridge', 'Random Forest', 'MLP']:
    q = qlike_results.get(name, np.nan)
    m = mse_results.get(name, np.nan)
    s = spearman_results.get(name, np.nan)
    if name in dm_results:
        dm_t = dm_results[name]['t_stat']
        dm_str = f"t={dm_t:+.3f}" if not np.isnan(dm_t) else "N/A"
    elif name == 'MF-GJR(VIX)':
        dm_str = "(benchmark)"
    else:
        dm_str = "N/A"
    print(f"  {name:20s} {q:10.4f} {m:12.4e} {s:10.4f} {dm_str:>15s}")

print(f"\n  Best model: {best_model} (QLIKE={qlike_results[best_model]:.4f})")
print(f"  Best ML: {best_ml_name} (QLIKE={best_ml_qlike:.4f})")
print("=" * 80)
