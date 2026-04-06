"""
K944: KAN-Inspired Nonlinear Vol Prediction (B-Spline Basis + GBR)

Building on K940 (MLP disaster, RF feasible but not beating MF-GJR(VIX)):
  - K940: MLP(32,16) QLIKE=651K (catastrophic), RF QLIKE=1.524 (OK but > MF-GJR 1.458)
  - K889: MF-GJR(VIX) is the best model (QLIKE=1.458, DM t=-4.42 vs GARCH)

KAN (Kolmogorov-Arnold Network, Liu et al. 2024) uses learnable B-spline
activation functions instead of fixed ReLU. Since pykan is not available on
Python 3.12, we implement the KAN concept manually:

1. **BSpline-Ridge (KAN proxy)**: Expand each feature with B-spline basis
   functions (degree 3, grid=5), then fit Ridge regression on the basis.
   This captures per-feature nonlinearity like KAN's phi_i(x_i).

2. **BSpline-GBR**: Same B-spline expansion + GradientBoostingRegressor.
   Tests if interaction terms beyond additive structure help.

3. **GradientBoosting (raw)**: Standard GBR on raw features (no spline expansion).
   Strong tree-based baseline that captures nonlinearities + interactions.

4. **Random Forest**: K940 baseline, reproduced here for comparison.

5. **GARCH(1,1)**: Parametric baseline.

6. **MF-GJR(VIX)**: Best known model (K889).

Features (ALL lagged, using t-1 info to predict t):
  1. sigma2_garch_{t-1}  (GARCH fitted variance)
  2. log(VIX_{t-1})
  3. r2_{t-1}            (squared return)
  4. |r_{t-1}|           (absolute return)
  5. YZ_{t-1}            (Yang-Zhang variance)
  6. rolling_var_20_{t-1} (20-day rolling variance)

Evaluation:
  - QLIKE on r2 (Patton 2011 proxy-robust)
  - MSE on r2
  - Spearman rho
  - DM test (Harvey |t| > 3.0)

Training protocol:
  - Expanding window, retrain every 63 trading days
  - Rolling z-score standardization (train window only)
  - Log-transform target (train on log(r2), predict exp(model output))
    to ensure positive predictions and QLIKE stability
  - OOS: 2016-01-01 ~ 2025-12-31
  - Seed: 42

References:
  Liu et al. (2024) "KAN: Kolmogorov-Arnold Networks" arXiv:2404.19756
  Patton (2011) "Volatility Forecast Comparison Using Imperfect Volatility Proxies"
  Harvey et al. (2016) "Tests for Forecast Encompassing"
  Christensen et al. (2023) "A Machine Learning Approach to Volatility Forecasting"
  Bucci (2020) "Realized Volatility Forecasting with Neural Networks"

Data source: yfinance (SPY + ^VIX), OHLC daily
Period: 2004-01-01 ~ 2025-12-31
OOS: 2016-01-01 ~ 2025-12-31
Window: expanding (from 2004), Refit: every 63 trading days
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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

import yfinance as yf
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.preprocessing import SplineTransformer

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K944: KAN-Inspired Nonlinear Vol Prediction")
print("=" * 60)

print("\n[1/7] Downloading data...")
spy = yf.download('SPY', start='2004-01-01', end='2026-01-01', progress=False, auto_adjust=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-01-01', progress=False, auto_adjust=False)

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

# 20-day rolling variance
spy['rolling_var_20'] = spy['r2'].rolling(window=20, min_periods=20).mean()

# Drop NaN
spy = spy.dropna(subset=['range_yz', 'log_return', 'r2', 'VIX', 'overnight_return',
                          'rolling_var_20'])

# Floor range
FLOOR = 1e-10
spy['range_yz'] = np.maximum(spy['range_yz'], FLOOR)

print(f"  Total observations: {len(spy)}")
print(f"  Date range: {spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}")

# Descriptive stats
print("\n  Descriptive Statistics:")
for name, col in [('r2', 'r2'), ('|r|', 'abs_r'), ('YZ Range', 'range_yz'), ('VIX', 'VIX')]:
    vals = spy[col]
    print(f"    {name:12s}: mean={vals.mean():.6f}, std={vals.std():.6f}, "
          f"skew={vals.skew():.3f}, kurt={vals.kurtosis():.3f}")

# ============================================================
# 2. GARCH / GJR / MF-GJR IMPLEMENTATIONS
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

    omega, alpha, gamma_coef, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma_coef, 'beta': beta,
            'persistence': alpha + 0.5*gamma_coef + beta, 'converged': result.success}


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


def mfgjr_fit(returns, vix_values, max_iter=500):
    """MF-GJR(VIX): GJR with VIX as multiplicative factor."""
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    v = np.asarray(vix_values, dtype=np.float64)
    mean_r2 = np.mean(r**2)

    # tau_t = delta0 + delta1 * VIX_t^2 / 252
    def neg_loglik(params):
        delta0, delta1, alpha, gamma, beta = params
        if alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5*gamma + beta) >= 0.9999:
            return 1e10

        tau = delta0 + delta1 * (v / 100)**2 / 252
        tau = np.maximum(tau, 1e-10)

        g = np.ones(T)
        for t in range(1, T):
            eps = r[t-1] / np.sqrt(tau[t-1] * g[t-1]) if tau[t-1] * g[t-1] > 0 else 0
            g[t] = 1 - alpha - 0.5*gamma - beta + alpha * eps**2 + gamma * eps**2 * (r[t-1] < 0) + beta * g[t-1]
            if g[t] <= 0.01:
                g[t] = 0.01
            if g[t] > 100:
                g[t] = 100

        h = tau * g
        h = np.maximum(h, 1e-10)
        ll = -0.5 * (np.log(2*np.pi) + np.log(h) + r**2 / h)
        return -np.sum(ll[10:])

    x0 = [mean_r2 * 0.1, 1.0, 0.02, 0.10, 0.85]
    bounds = [(1e-10, None), (0.01, 10.0), (1e-8, 0.5), (0.0, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for d0, d1, a0, g0, b0 in [(mean_r2*0.05, 0.5, 0.01, 0.15, 0.85),
                                      (mean_r2*0.02, 2.0, 0.03, 0.08, 0.88)]:
            x0_alt = [d0, d1, a0, g0, b0]
            r_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                             options={'maxiter': max_iter, 'ftol': 1e-12})
            if r_alt.success and r_alt.fun < result.fun:
                result = r_alt

    delta0, delta1, alpha, gamma_coef, beta = result.x
    return {'delta0': delta0, 'delta1': delta1, 'alpha': alpha,
            'gamma': gamma_coef, 'beta': beta,
            'persistence': alpha + 0.5*gamma_coef + beta,
            'converged': result.success}


def mfgjr_variance_path(params, returns, vix_values):
    """Compute MF-GJR variance path."""
    T = len(returns)
    r = np.asarray(returns, dtype=np.float64)
    v = np.asarray(vix_values, dtype=np.float64)

    tau = params['delta0'] + params['delta1'] * (v / 100)**2 / 252
    tau = np.maximum(tau, 1e-10)

    alpha, gamma, beta = params['alpha'], params['gamma'], params['beta']

    g = np.ones(T)
    for t in range(1, T):
        eps = r[t-1] / np.sqrt(tau[t-1] * g[t-1]) if tau[t-1] * g[t-1] > 0 else 0
        g[t] = 1 - alpha - 0.5*gamma - beta + alpha * eps**2 + gamma * eps**2 * (r[t-1] < 0) + beta * g[t-1]
        if g[t] <= 0.01:
            g[t] = 0.01
        if g[t] > 100:
            g[t] = 100

    return tau * g


# ============================================================
# 3. OOS EXPANDING WINDOW
# ============================================================
print("\n[3/7] OOS expanding window predictions...")

oos_start = '2016-01-01'
oos_mask = spy.index >= oos_start
oos_idx = spy.index[oos_mask]
n_oos = len(oos_idx)
print(f"  OOS: {oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}, N={n_oos}")

REFIT_EVERY = 63

# Feature columns (all lagged by 1 day naturally since we use t-1 values)
FEATURE_COLS = ['garch_var', 'log_VIX', 'r2', 'abs_r', 'range_yz', 'rolling_var_20']

# Prepare feature matrix: each feature uses t-1 value to predict t
# We create a lagged feature DataFrame
feat_df = pd.DataFrame(index=spy.index)
feat_df['garch_var'] = np.nan  # Will be filled by GARCH path
feat_df['log_VIX'] = spy['log_VIX'].shift(1)  # t-1
feat_df['r2'] = spy['r2'].shift(1)  # t-1
feat_df['abs_r'] = spy['abs_r'].shift(1)  # t-1
feat_df['range_yz'] = spy['range_yz'].shift(1)  # t-1
feat_df['rolling_var_20'] = spy['rolling_var_20'].shift(1)  # t-1

# Target
target = spy['r2']

# Storage for OOS predictions
preds = {
    'GARCH(1,1)': np.full(n_oos, np.nan),
    'GJR(1,1,1)': np.full(n_oos, np.nan),
    'MF-GJR(VIX)': np.full(n_oos, np.nan),
    'BSpline-Ridge': np.full(n_oos, np.nan),
    'BSpline-GBR': np.full(n_oos, np.nan),
    'GBR': np.full(n_oos, np.nan),
    'RF': np.full(n_oos, np.nan),
}

oos_actual = spy['r2'][oos_mask].values

# Track last fit parameters
last_garch = None
last_gjr = None
last_mfgjr = None

# B-spline config (KAN proxy)
N_KNOTS = 5  # number of knots per feature
SPLINE_DEGREE = 3

n_refits = 0
for i in range(n_oos):
    t_idx = spy.index.get_loc(oos_idx[i])

    # Determine if we need to refit
    do_refit = (i == 0) or (i % REFIT_EVERY == 0)

    if do_refit:
        n_refits += 1
        train_returns = spy['log_return'].iloc[:t_idx].values
        train_vix = spy['VIX'].iloc[:t_idx].values

        # Fit GARCH
        last_garch = garch_fit(train_returns)
        # Fit GJR
        last_gjr = gjr_fit(train_returns)
        # Fit MF-GJR(VIX)
        last_mfgjr = mfgjr_fit(train_returns, train_vix)

        if i % (REFIT_EVERY * 5) == 0:
            print(f"  Refit {n_refits}: t={i}/{n_oos}, "
                  f"GARCH persistence={last_garch['persistence']:.4f}, "
                  f"GJR persistence={last_gjr['persistence']:.4f}, "
                  f"MF-GJR persistence={last_mfgjr['persistence']:.4f}")

    # === GARCH/GJR/MF-GJR OOS forecasts (recursive 1-step) ===
    all_returns = spy['log_return'].iloc[:t_idx+1].values
    all_vix = spy['VIX'].iloc[:t_idx+1].values

    # GARCH forecast: h[t] = omega + alpha * r[t-1]^2 + beta * h[t-1]
    garch_h = garch_variance_path(last_garch, all_returns)
    preds['GARCH(1,1)'][i] = garch_h[-1]  # h[t] uses r[t-1], h[t-1] -- no lookahead

    # GJR forecast
    gjr_h = gjr_variance_path(last_gjr, all_returns)
    preds['GJR(1,1,1)'][i] = gjr_h[-1]

    # MF-GJR(VIX) forecast
    mfgjr_h = mfgjr_variance_path(last_mfgjr, all_returns, all_vix)
    preds['MF-GJR(VIX)'][i] = mfgjr_h[-1]

    # Fill garch_var feature for ML models
    feat_df.iloc[t_idx, feat_df.columns.get_loc('garch_var')] = garch_h[-2] if len(garch_h) > 1 else garch_h[-1]

    # === ML models (only at refit points we retrain, otherwise use existing model) ===
    if do_refit:
        # Prepare training data
        # Need garch_var for ALL training dates: recompute full GARCH path
        train_garch_h = garch_variance_path(last_garch, train_returns)

        # Build training feature matrix
        train_feat = pd.DataFrame(index=spy.index[:t_idx])
        train_feat['garch_var'] = train_garch_h
        train_feat['log_VIX'] = spy['log_VIX'].iloc[:t_idx].values
        train_feat['r2'] = spy['r2'].iloc[:t_idx].values
        train_feat['abs_r'] = spy['abs_r'].iloc[:t_idx].values
        train_feat['range_yz'] = spy['range_yz'].iloc[:t_idx].values
        train_feat['rolling_var_20'] = spy['rolling_var_20'].iloc[:t_idx].values

        # Lag all features by 1 (predict t using t-1)
        train_X_raw = train_feat.shift(1).iloc[1:].values  # drop first NaN row
        train_y = spy['r2'].iloc[1:t_idx].values  # target: r2[t]

        # Remove any remaining NaN
        valid = ~np.isnan(train_X_raw).any(axis=1) & ~np.isnan(train_y)
        train_X_raw = train_X_raw[valid]
        train_y = train_y[valid]

        # Standardize (rolling z-score using training data only)
        train_mean = train_X_raw.mean(axis=0)
        train_std = train_X_raw.std(axis=0) + 1e-10
        train_X_std = (train_X_raw - train_mean) / train_std

        # Train ML models on raw r² (RF/GBR naturally produce positive predictions
        # from tree averaging). BSpline-Ridge uses log-target since linear models
        # can produce negative predictions.
        train_y_log = np.log(np.maximum(train_y, FLOOR))

        # 1. BSpline-Ridge (KAN proxy) — train on log(r²), predict exp()
        # sklearn SplineTransformer creates B-spline basis for each feature
        spline_transformer = SplineTransformer(
            n_knots=N_KNOTS, degree=SPLINE_DEGREE,
            extrapolation='linear', include_bias=False
        )
        train_X_spline = spline_transformer.fit_transform(train_X_std)

        bspline_ridge = Ridge(alpha=1.0)
        bspline_ridge.fit(train_X_spline, train_y_log)

        # 2. BSpline-GBR — train on raw r² (tree-based, positive predictions)
        bspline_gbr = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            min_samples_leaf=20, random_state=42
        )
        bspline_gbr.fit(train_X_spline, train_y)

        # 3. GBR (raw features) — train on raw r²
        gbr_model = GradientBoostingRegressor(
            n_estimators=100, max_depth=3, learning_rate=0.05,
            min_samples_leaf=20, random_state=42
        )
        gbr_model.fit(train_X_std, train_y)

        # 4. Random Forest — train on raw r²
        rf_model = RandomForestRegressor(
            n_estimators=100, max_depth=5, min_samples_leaf=10,
            random_state=42
        )
        rf_model.fit(train_X_std, train_y)

    # Predict for current OOS day
    # Build feature vector for t using t-1 data
    feat_vec = np.array([
        feat_df.iloc[t_idx, feat_df.columns.get_loc('garch_var')],
        feat_df.iloc[t_idx, feat_df.columns.get_loc('log_VIX')],
        feat_df.iloc[t_idx, feat_df.columns.get_loc('r2')],
        feat_df.iloc[t_idx, feat_df.columns.get_loc('abs_r')],
        feat_df.iloc[t_idx, feat_df.columns.get_loc('range_yz')],
        feat_df.iloc[t_idx, feat_df.columns.get_loc('rolling_var_20')],
    ]).reshape(1, -1)

    if np.isnan(feat_vec).any():
        # Use GARCH prediction as fallback
        for m in ['BSpline-Ridge', 'BSpline-GBR', 'GBR', 'RF']:
            preds[m][i] = preds['GARCH(1,1)'][i]
        continue

    # Standardize
    feat_vec_std = (feat_vec - train_mean) / train_std

    # BSpline-Ridge prediction (log-space → exp back, since Ridge can go negative)
    feat_vec_spline = spline_transformer.transform(feat_vec_std)
    pred_bsr = np.exp(bspline_ridge.predict(feat_vec_spline)[0])
    preds['BSpline-Ridge'][i] = max(pred_bsr, FLOOR)

    # BSpline-GBR prediction (raw r², tree-based)
    # Floor at 1% of training mean r² to avoid QLIKE explosion from near-zero
    min_pred = train_y.mean() * 0.01
    pred_bsgbr = bspline_gbr.predict(feat_vec_spline)[0]
    preds['BSpline-GBR'][i] = max(pred_bsgbr, min_pred)

    # GBR prediction (raw r², tree-based)
    pred_gbr = gbr_model.predict(feat_vec_std)[0]
    preds['GBR'][i] = max(pred_gbr, min_pred)

    # RF prediction (raw r², tree-based)
    pred_rf = rf_model.predict(feat_vec_std)[0]
    preds['RF'][i] = max(pred_rf, min_pred)


print(f"  Total refits: {n_refits}")

# ============================================================
# 4. EVALUATION
# ============================================================
print("\n[4/7] Evaluation metrics...")

results = {}
for model_name, pred_vals in preds.items():
    # Floor predictions
    pred_vals = np.maximum(pred_vals, FLOOR)

    q = qlike(oos_actual, pred_vals)
    mse = np.mean((oos_actual - pred_vals)**2)
    spearman_r, spearman_p = stats.spearmanr(oos_actual, pred_vals)

    results[model_name] = {
        'qlike': q,
        'mse': mse,
        'spearman_rho': spearman_r,
        'spearman_p': spearman_p,
    }

    print(f"  {model_name:20s}: QLIKE={q:.4f}, MSE={mse:.2e}, "
          f"Spearman={spearman_r:.4f} (p={spearman_p:.4f})")

# ============================================================
# 5. DM TESTS
# ============================================================
print("\n[5/7] DM tests (Harvey |t| > 3.0 threshold)...")

# Reference model: MF-GJR(VIX)
ref = 'MF-GJR(VIX)'
ref_pred = np.maximum(preds[ref], FLOOR)
ref_loss = qlike_pointwise(oos_actual, ref_pred)

dm_results = {}
for model_name, pred_vals in preds.items():
    if model_name == ref:
        continue
    pred_vals = np.maximum(pred_vals, FLOOR)
    model_loss = qlike_pointwise(oos_actual, pred_vals)

    # Use project's DM test implementation
    dm_stat, dm_pval = dm_test(ref_loss, model_loss)

    # Negative t: ref is better; Positive t: model is better
    dm_results[model_name] = {
        'dm_stat': dm_stat,
        'dm_pval': dm_pval,
        'significant': abs(dm_stat) > 3.0,
        'winner': ref if dm_stat < 0 else model_name
    }

    sig_str = "***" if abs(dm_stat) > 3.0 else ""
    print(f"  {ref} vs {model_name:20s}: DM t={dm_stat:.4f}, p={dm_pval:.4f} {sig_str}")

# Also test BSpline-Ridge vs RF and GBR
print("\n  Pairwise comparisons (KAN-proxy models):")
pairwise_dm = {}
for m1, m2 in [('BSpline-Ridge', 'RF'), ('BSpline-Ridge', 'GBR'),
               ('BSpline-GBR', 'RF'), ('BSpline-GBR', 'GBR'),
               ('GBR', 'RF')]:
    l1 = qlike_pointwise(oos_actual, np.maximum(preds[m1], FLOOR))
    l2 = qlike_pointwise(oos_actual, np.maximum(preds[m2], FLOOR))
    dm_s, dm_p = dm_test(l1, l2)
    sig_str = "***" if abs(dm_s) > 3.0 else ""
    print(f"    {m1} vs {m2}: DM t={dm_s:.4f}, p={dm_p:.4f} {sig_str}")
    pairwise_dm[f"{m1}_vs_{m2}"] = {'dm_stat': dm_s, 'dm_pval': dm_p}

# ============================================================
# 6. FEATURE IMPORTANCE (from GBR and RF)
# ============================================================
print("\n[6/7] Feature importance analysis...")

feature_names = FEATURE_COLS
print("\n  GBR Feature Importances (last refit):")
gbr_imp = gbr_model.feature_importances_
for fname, imp in sorted(zip(feature_names, gbr_imp), key=lambda x: -x[1]):
    print(f"    {fname:20s}: {imp:.4f}")

print("\n  RF Feature Importances (last refit):")
rf_imp = rf_model.feature_importances_
for fname, imp in sorted(zip(feature_names, rf_imp), key=lambda x: -x[1]):
    print(f"    {fname:20s}: {imp:.4f}")

# BSpline-Ridge: coefficient magnitudes by feature group
n_spline_per_feat = train_X_spline.shape[1] // len(feature_names)
bsr_importance = []
for j, fname in enumerate(feature_names):
    start = j * n_spline_per_feat
    end = (j + 1) * n_spline_per_feat
    if end > len(bspline_ridge.coef_):
        end = len(bspline_ridge.coef_)
    imp = np.sum(np.abs(bspline_ridge.coef_[start:end]))
    bsr_importance.append(imp)

# Normalize
total_imp = sum(bsr_importance)
bsr_importance = [x / total_imp for x in bsr_importance]

print("\n  BSpline-Ridge Feature Importances (coefficient magnitude, normalized):")
for fname, imp in sorted(zip(feature_names, bsr_importance), key=lambda x: -x[1]):
    print(f"    {fname:20s}: {imp:.4f}")

# ============================================================
# 7. PLOTS + SAVE
# ============================================================
print("\n[7/7] Generating plots and saving results...")

# Plot 1: QLIKE comparison bar chart
fig, ax = plt.subplots(1, 1, figsize=(10, 6))
models_sorted = sorted(results.keys(), key=lambda m: results[m]['qlike'])
qlike_vals = [results[m]['qlike'] for m in models_sorted]
colors = ['#2ecc71' if m == 'MF-GJR(VIX)' else
          '#e74c3c' if m.startswith('BSpline') else
          '#3498db' if m in ['GBR', 'RF'] else '#95a5a6'
          for m in models_sorted]
bars = ax.barh(models_sorted, qlike_vals, color=colors)
ax.set_xlabel('QLIKE (lower is better)')
ax.set_title('K944: QLIKE Comparison (OOS 2016-2025)')
ax.axvline(results['MF-GJR(VIX)']['qlike'], color='green', linestyle='--', alpha=0.5, label='MF-GJR(VIX)')

# Add value labels
for bar, val in zip(bars, qlike_vals):
    if val < 100:  # Only label reasonable values
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height()/2,
                f'{val:.4f}', va='center', fontsize=9)

ax.legend()
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k944_comparison.png'), dpi=150)
plt.close()

# Plot 2: Rolling QLIKE (252-day window)
fig, ax = plt.subplots(1, 1, figsize=(12, 6))
window_roll = 252
models_to_plot = ['GARCH(1,1)', 'MF-GJR(VIX)', 'BSpline-Ridge', 'GBR', 'RF']
colors_roll = {'GARCH(1,1)': '#95a5a6', 'MF-GJR(VIX)': '#2ecc71',
               'BSpline-Ridge': '#e74c3c', 'GBR': '#3498db', 'RF': '#9b59b6'}

for model_name in models_to_plot:
    pred_vals = np.maximum(preds[model_name], FLOOR)
    pw = qlike_pointwise(oos_actual, pred_vals)
    rolling = pd.Series(pw, index=oos_idx).rolling(window_roll, min_periods=window_roll).mean()
    ax.plot(rolling.index, rolling.values, label=model_name, color=colors_roll.get(model_name, 'gray'))

ax.set_ylabel('Rolling QLIKE (252-day)')
ax.set_title('K944: Rolling QLIKE Over Time')
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k944_rolling_qlike.png'), dpi=150)
plt.close()

# Plot 3: Feature importance comparison
fig, axes = plt.subplots(1, 3, figsize=(15, 5))

for ax_i, (title, importances) in enumerate([
    ('BSpline-Ridge', bsr_importance),
    ('GBR', list(gbr_imp)),
    ('RF', list(rf_imp))
]):
    sorted_pairs = sorted(zip(feature_names, importances), key=lambda x: x[1])
    names, vals = zip(*sorted_pairs)
    axes[ax_i].barh(names, vals, color='#3498db')
    axes[ax_i].set_title(f'{title} Feature Importance')
    axes[ax_i].set_xlabel('Importance')

plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k944_feature_importance.png'), dpi=150)
plt.close()

# ============================================================
# 8. SAVE RESULTS JSON
# ============================================================

# Determine best ML model
ml_models = ['BSpline-Ridge', 'BSpline-GBR', 'GBR', 'RF']
best_ml = min(ml_models, key=lambda m: results[m]['qlike'])
best_ml_qlike = results[best_ml]['qlike']
mfgjr_qlike = results['MF-GJR(VIX)']['qlike']

conclusion = (
    f"Best ML model: {best_ml} (QLIKE={best_ml_qlike:.4f}). "
    f"MF-GJR(VIX) QLIKE={mfgjr_qlike:.4f}. "
)

if best_ml_qlike < mfgjr_qlike:
    dm_info = dm_results.get(best_ml, {})
    if dm_info.get('significant', False):
        conclusion += f"ML beats MF-GJR significantly (DM t={dm_info['dm_stat']:.3f})."
    else:
        conclusion += f"ML numerically better but not statistically significant (DM t={dm_info.get('dm_stat', 'N/A')})."
else:
    conclusion += "MF-GJR(VIX) still dominant. KAN-style nonlinear methods do not improve over parametric models for daily vol prediction."

print(f"\n  {conclusion}")

output = {
    'experiment_id': 'K944',
    'title': 'KAN-Inspired Nonlinear Vol Prediction (BSpline Basis + GBR)',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY + ^VIX)',
    'period': f"{spy.index[0].strftime('%Y-%m-%d')} ~ {spy.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')}",
    'n_oos': n_oos,
    'n_refits': n_refits,
    'refit_every': REFIT_EVERY,
    'window_type': 'expanding (from 2004)',
    'seed': 42,
    'models': {
        'traditional': ['GARCH(1,1)', 'GJR(1,1,1)', 'MF-GJR(VIX)'],
        'ml': ['BSpline-Ridge (KAN proxy)', 'BSpline-GBR', 'GBR', 'RF'],
    },
    'kan_implementation_note': (
        'pykan 0.0.5 installed in Python 3.9 (anaconda) but experiment runs on Python 3.12. '
        'KAN concept implemented via sklearn SplineTransformer (B-spline basis expansion) + Ridge/GBR. '
        'This captures the key KAN idea: learnable per-feature nonlinearity via B-spline basis.'
    ),
    'features': FEATURE_COLS,
    'bspline_config': {
        'n_knots': N_KNOTS,
        'degree': SPLINE_DEGREE,
        'n_basis_per_feature': n_spline_per_feat,
        'total_spline_features': train_X_spline.shape[1],
    },
    'ml_config': {
        'BSpline-Ridge': {'alpha': 1.0, 'n_spline_features': train_X_spline.shape[1]},
        'BSpline-GBR': {'n_estimators': 100, 'max_depth': 3, 'lr': 0.05, 'min_samples_leaf': 20},
        'GBR': {'n_estimators': 100, 'max_depth': 3, 'lr': 0.05, 'min_samples_leaf': 20},
        'RF': {'n_estimators': 100, 'max_depth': 5, 'min_samples_leaf': 10},
    },
    'results': {
        'qlike': {m: round(r['qlike'], 4) for m, r in results.items()},
        'mse': {m: r['mse'] for m, r in results.items()},
        'spearman_rho': {m: round(r['spearman_rho'], 4) for m, r in results.items()},
    },
    'dm_tests_vs_mfgjr': {
        m: {
            'dm_stat': round(v['dm_stat'], 4),
            'dm_pval': round(v['dm_pval'], 6),
            'significant_harvey': v['significant'],
            'winner': v['winner'],
        } for m, v in dm_results.items()
    },
    'pairwise_dm': {
        k: {'dm_stat': round(v['dm_stat'], 4), 'dm_pval': round(v['dm_pval'], 6)}
        for k, v in pairwise_dm.items()
    },
    'feature_importance': {
        'BSpline-Ridge': {f: round(imp, 4) for f, imp in zip(feature_names, bsr_importance)},
        'GBR': {f: round(float(imp), 4) for f, imp in zip(feature_names, gbr_imp)},
        'RF': {f: round(float(imp), 4) for f, imp in zip(feature_names, rf_imp)},
    },
    'conclusion': conclusion,
    'hypotheses': {
        'H1': 'BSpline-Ridge (KAN proxy) captures nonlinearities missed by MF-GJR → beats in QLIKE',
        'H2': 'ML approx MF-GJR → parametric structure already sufficient',
        'H3': 'ML < GARCH → overfitting on daily SNR',
    },
    'references': [
        'Liu et al. (2024) KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756',
        'Patton (2011) Volatility Forecast Comparison Using Imperfect Volatility Proxies, JoE',
        'Harvey et al. (2016) Tests for Forecast Encompassing',
        'Christensen et al. (2023) A Machine Learning Approach to Volatility Forecasting',
        'Bucci (2020) Realized Volatility Forecasting with Neural Networks, JIMF',
    ],
}

with open(os.path.join(SCRIPT_DIR, 'k944_results.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {os.path.join(SCRIPT_DIR, 'k944_results.json')}")
print(f"  Plots saved: k944_comparison.png, k944_rolling_qlike.png, k944_feature_importance.png")
print(f"\n{'='*60}")
print(f"K944 COMPLETE: {conclusion}")
print(f"{'='*60}")
