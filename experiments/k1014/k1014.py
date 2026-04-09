#!/usr/bin/env python3
"""
K1014: HAR-PD (Path-Dependent) Volatility Forecasting
======================================================
[提出: Claude, 執行: Claude]

Motivation:
  K530 found HAR-ABS crushes GJR with DM=-15.45. But standard HAR uses
  only level-based features (RV1, RV5, RV22), ignoring the *shape* of
  the volatility path. arXiv:2503.00851 proposes path-dependent features
  to capture trends, convexity, and momentum in the vol path.

  This experiment tests whether path-dependent features improve HAR
  forecasting, and compares HAR-PD against the A4f multiplicative
  GARCH-X model (K988's best specification).

Models:
  1. HAR:          Standard HAR(1,5,22) on |r| (K530 baseline)
  2. HAR-PD:       HAR + 6 path-dependent features
  3. HAR-PD-LASSO: HAR + LASSO-selected path features
  4. A4f-N:        MF-GJR-X (tau = theta0 + theta1 * VIX^2, free omega)
  5. GJR-N:        Standard GJR-GARCH(1,1)

Path features:
  TREND:   RV_5d - RV_22d (short vs long-term trend)
  CONVEX:  RV_1d - 2*RV_5d + RV_22d (second-order difference)
  MOM:     RV_1d / RV_5d - 1 (recent momentum)
  JUMP:    max(|r|) over 5d / RV_5d - 1 (jump proxy)
  ASYM:    sum(r^2 where r<0) / sum(r^2) over 5d (downside fraction)
  VIX_GAP: VIX_daily_vol - RV_5d (implied-realized gap)

References:
  - arXiv:2503.00851: Path-dependent HAR
  - Corsi (2009, JFE): Original HAR-RV
  - Patton (2011, J Econometrics): QLIKE proxy-robust loss
  - Harvey et al. (2016): t > 3.0 threshold
  - K530: HAR-ABS DM=-15.45 vs GJR
  - K988: MF-GJR-X A4f specification

Data: SPY 2005-2026 from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r² (Patton 2011), pairwise DM tests, Spearman ρ.

Usage:
    uv run python experiments/k1014/k1014.py
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

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1014"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1014_results.json')
PLOT_PATH = os.path.join(SCRIPT_DIR, 'k1014_comparison.png')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
HAR_WINDOW = 1000      # rolling OLS window for HAR
GARCH_WINDOW = 2000    # rolling window for GARCH models
REFIT_EVERY = 63       # quarterly refit for GARCH

print("=" * 70)
print(f"{EXPERIMENT_ID}: HAR-PD (Path-Dependent) Volatility Forecasting")
print("  HAR + path features vs A4f-N vs GJR benchmark")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = int(oos_mask.sum())
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
print(f"  OOS mean return (ann): {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std (ann): {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")

# ============================================================
# SECTION 3: FEATURE CONSTRUCTION
# ============================================================
print("\n[3] Building HAR and path-dependent features...")

abs_r = np.abs(ret)

# Standard HAR features: rolling means of |r|
rv1 = abs_r.copy()
rv5 = pd.Series(abs_r, index=df.index).rolling(5).mean().values
rv22 = pd.Series(abs_r, index=df.index).rolling(22).mean().values

# Path-dependent features
# TREND: short-term vs long-term
trend = rv5 - rv22

# CONVEX: second-order difference (acceleration)
convex = rv1 - 2 * rv5 + rv22

# MOM: recent momentum
mom = np.where(rv5 > 1e-10, rv1 / rv5 - 1.0, 0.0)

# JUMP proxy: max |r| over 5 days / mean |r| over 5 days - 1
abs_r_series = pd.Series(abs_r, index=df.index)
max5 = abs_r_series.rolling(5).max().values
jump = np.where(rv5 > 1e-10, max5 / rv5 - 1.0, 0.0)

# ASYM: fraction of squared returns from negative days (5-day window)
r_series = pd.Series(ret, index=df.index)
neg_sq = pd.Series(np.where(ret < 0, ret**2, 0.0), index=df.index)
all_sq = pd.Series(ret**2, index=df.index)
neg_sq_5 = neg_sq.rolling(5).sum().values
all_sq_5 = all_sq.rolling(5).sum().values
asym = np.where(all_sq_5 > 1e-16, neg_sq_5 / all_sq_5, 0.5)

# VIX_GAP: implied daily vol - realized 5d vol
vix_daily_vol = vix / np.sqrt(252) / 100.0  # VIX is annualized %
vix_gap = vix_daily_vol - rv5

# Target: next-day |r| (HAR target, shifted properly)
target_abs = np.roll(abs_r, -1)
target_abs[-1] = np.nan

# Build feature matrix
features = pd.DataFrame({
    'rv1': rv1,
    'rv5': rv5,
    'rv22': rv22,
    'trend': trend,
    'convex': convex,
    'mom': mom,
    'jump': jump,
    'asym': asym,
    'vix_gap': vix_gap,
    'target_abs': target_abs,
}, index=df.index)

# Drop NaN rows (from rolling windows)
valid_mask = features.notna().all(axis=1)
features = features[valid_mask]
# Also need to track which OOS dates survive
feat_oos_mask = np.array(features.index >= OOS_START)

print(f"  Valid features: {len(features)}, OOS: {feat_oos_mask.sum()}")
print(f"  Path feature stats (full sample):")
for col in ['trend', 'convex', 'mom', 'jump', 'asym', 'vix_gap']:
    vals = features[col].values
    print(f"    {col:10s}: mean={np.mean(vals):.6f}, std={np.std(vals):.6f}")

# ============================================================
# SECTION 4: UTILITY FUNCTIONS
# ============================================================

def qlike_loss(realized, forecast):
    """QLIKE: mean(realized/forecast - log(realized/forecast) - 1)."""
    ratio = realized / forecast
    return float(np.mean(ratio - np.log(ratio) - 1))

def qlike_loss_array(realized, forecast):
    """Element-wise QLIKE."""
    ratio = realized / forecast
    return ratio - np.log(ratio) - 1

def dm_test_func(loss1, loss2, h=1):
    """Diebold-Mariano test. Negative DM => model 1 better."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=0)
    var_d = gamma_0 / T
    if var_d <= 0:
        return (0.0, 1.0)
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return (float(dm_stat), float(p_value))

def ols_fit(X, y):
    """OLS with intercept."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    return beta

def ols_predict(X_new, beta):
    """Predict with OLS coefficients."""
    x_aug = np.concatenate([[1.0], X_new])
    return max(np.dot(x_aug, beta), 1e-10)

# ============================================================
# SECTION 5: HAR MODELS — ROLLING OOS FORECASTS
# ============================================================
print("\n[4] Running HAR models (rolling OOS)...")

feat_vals = features.values
feat_cols = features.columns.tolist()
col_idx = {c: i for i, c in enumerate(feat_cols)}
n_feat = len(features)

# Indices for features
har_cols = [col_idx['rv1'], col_idx['rv5'], col_idx['rv22']]
path_cols = [col_idx['trend'], col_idx['convex'], col_idx['mom'],
             col_idx['jump'], col_idx['asym'], col_idx['vix_gap']]
all_pd_cols = har_cols + path_cols
target_idx = col_idx['target_abs']

# Storage for OOS forecasts
oos_indices = np.where(feat_oos_mask)[0]
n_oos_har = len(oos_indices)

har_fcst = np.zeros(n_oos_har)
har_pd_fcst = np.zeros(n_oos_har)
har_pd_lasso_fcst = np.zeros(n_oos_har)
har_target = np.zeros(n_oos_har)

print(f"  HAR rolling window={HAR_WINDOW}, OOS points={n_oos_har}")

# Try importing sklearn for LASSO
try:
    from sklearn.linear_model import LassoCV
    HAS_SKLEARN = True
    print("  sklearn available — LASSO CV will be used")
except ImportError:
    HAS_SKLEARN = False
    print("  sklearn not available — using Ridge fallback for regularization")

for i, t in enumerate(oos_indices):
    if i % 200 == 0:
        print(f"    HAR OOS: {i}/{n_oos_har}")

    # Training window
    t_start = max(0, t - HAR_WINDOW)
    train_data = feat_vals[t_start:t]
    X_train_har = train_data[:, har_cols]
    X_train_pd = train_data[:, all_pd_cols]
    y_train = train_data[:, target_idx]

    # Remove any NaN
    valid = ~np.isnan(y_train)
    X_train_har = X_train_har[valid]
    X_train_pd = X_train_pd[valid]
    y_train = y_train[valid]

    if len(y_train) < 50:
        har_fcst[i] = np.mean(np.abs(ret)) if i == 0 else har_fcst[i-1]
        har_pd_fcst[i] = har_fcst[i]
        har_pd_lasso_fcst[i] = har_fcst[i]
        har_target[i] = feat_vals[t, target_idx]
        continue

    # Current features for prediction
    x_now_har = feat_vals[t, har_cols]
    x_now_pd = feat_vals[t, all_pd_cols]

    # 1. HAR standard
    beta_har = ols_fit(X_train_har, y_train)
    har_fcst[i] = ols_predict(x_now_har, beta_har)

    # 2. HAR-PD (all path features)
    beta_pd = ols_fit(X_train_pd, y_train)
    har_pd_fcst[i] = ols_predict(x_now_pd, beta_pd)

    # 3. HAR-PD-LASSO
    if HAS_SKLEARN:
        try:
            X_aug_train = np.column_stack([np.ones(len(y_train)), X_train_pd])
            lasso = LassoCV(cv=5, random_state=42, max_iter=5000, n_alphas=20)
            lasso.fit(X_aug_train[:, 1:], y_train)  # LassoCV adds intercept internally? No.
            # Manually: use LassoCV on centered data
            lasso = LassoCV(cv=5, random_state=42, max_iter=5000, n_alphas=20,
                            fit_intercept=True)
            lasso.fit(X_train_pd, y_train)
            x_pred = np.atleast_2d(x_now_pd)
            pred = lasso.predict(x_pred)[0]
            har_pd_lasso_fcst[i] = max(pred, 1e-10)
        except Exception:
            har_pd_lasso_fcst[i] = har_pd_fcst[i]
    else:
        # Ridge fallback
        lam = 0.01
        X_aug = np.column_stack([np.ones(len(y_train)), X_train_pd])
        I = np.eye(X_aug.shape[1])
        I[0, 0] = 0  # Don't regularize intercept
        beta_ridge = np.linalg.solve(X_aug.T @ X_aug + lam * I, X_aug.T @ y_train)
        x_aug_new = np.concatenate([[1.0], x_now_pd])
        har_pd_lasso_fcst[i] = max(np.dot(x_aug_new, beta_ridge), 1e-10)

    har_target[i] = feat_vals[t, target_idx]

print(f"  HAR done in {time.time() - START_TIME:.1f}s")

# ============================================================
# SECTION 6: GJR-GARCH AND A4f MODELS
# ============================================================
print("\n[5] Running GJR-GARCH and A4f models...")

# We need to align OOS dates between HAR features and raw data
# HAR features start after 22 days of rolling; GARCH uses raw returns
# We'll compute GARCH forecasts on the raw ret series, then align

# Get OOS dates from HAR features
oos_dates = features.index[feat_oos_mask]

# Map these dates to positions in the original df
date_to_raw_idx = {d: i for i, d in enumerate(df.index)}
raw_oos_indices = np.array([date_to_raw_idx[d] for d in oos_dates])

gjr_fcst = np.zeros(n_oos_har)
a4f_fcst = np.zeros(n_oos_har)

# --- GJR-GARCH(1,1) ---
print("  Fitting GJR-GARCH(1,1)...")

def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) via MLE."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik_pure, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params

def gjr_loglik_pure(params, returns):
    """GJR-GARCH(1,1) negative log-likelihood (pure Python for scipy)."""
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

# GJR with quarterly refit
gjr_params = None
gjr_h_prev = None
last_gjr_refit = -REFIT_EVERY

for i, raw_t in enumerate(raw_oos_indices):
    if i % 200 == 0:
        print(f"    GJR OOS: {i}/{n_oos_har}")

    # Refit check
    if i - last_gjr_refit >= REFIT_EVERY or gjr_params is None:
        train_start = max(0, raw_t - GARCH_WINDOW)
        train_ret = ret[train_start:raw_t]
        gjr_params = fit_gjr(train_ret)
        if gjr_params is None:
            gjr_params = np.array([np.var(train_ret) * 0.05, 0.05, 0.05, 0.90])

        # Run GARCH filter on training data to get h[T]
        omega, alpha, gamma, beta = gjr_params
        h = np.var(train_ret[:min(250, len(train_ret))])
        for tt in range(1, len(train_ret)):
            r_prev = train_ret[tt - 1]
            asym = gamma * r_prev**2 if r_prev < 0 else 0.0
            h = omega + alpha * r_prev**2 + asym + beta * h
            h = max(h, 1e-10)
        gjr_h_prev = h
        last_gjr_refit = i

    # 1-step forecast
    omega, alpha, gamma, beta = gjr_params
    r_prev = ret[raw_t - 1]
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    gjr_h = omega + alpha * r_prev**2 + asym + beta * gjr_h_prev
    gjr_h = max(gjr_h, 1e-10)
    gjr_fcst[i] = gjr_h
    gjr_h_prev = gjr_h

print(f"  GJR done in {time.time() - START_TIME:.1f}s")

# --- A4f Model: MF-GJR-X (tau = theta0 + theta1 * VIX^2, free omega) ---
print("  Fitting A4f MF-GJR-X model...")

log_vix = np.log(np.maximum(vix, 1.0))

def fit_a4f(returns, vix_vals):
    """Fit A4f: tau = max(theta0 + theta1 * VIX^2_{t-1}, eps), g has free omega."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
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
    starts = [
        [var0 * 0.5, var0 / vix2_mean * 0.5, 0.05, 0.05, 0.05, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 0.8, 0.02, 0.03, 0.08, 0.86],
        [var0 * 0.8, var0 / vix2_mean * 0.2, 0.08, 0.08, 0.10, 0.78],
    ]
    bounds = [
        (-var0 * 2, var0 * 5),       # theta0
        (1e-10, var0 / vix2_mean * 5),  # theta1
        (1e-6, 0.5),                  # omega_g
        (1e-4, 0.3),                  # alpha
        (1e-4, 0.3),                  # gamma
        (0.5, 0.999),                 # beta
    ]

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params

# A4f with quarterly refit
a4f_params = None
a4f_g_prev = None
last_a4f_refit = -REFIT_EVERY

for i, raw_t in enumerate(raw_oos_indices):
    if i % 200 == 0:
        print(f"    A4f OOS: {i}/{n_oos_har}")

    if i - last_a4f_refit >= REFIT_EVERY or a4f_params is None:
        train_start = max(0, raw_t - GARCH_WINDOW)
        train_ret = ret[train_start:raw_t]
        train_vix = vix[train_start:raw_t]

        a4f_params = fit_a4f(train_ret, train_vix)
        if a4f_params is None:
            # Fallback
            a4f_params = np.array([np.var(train_ret) * 0.5,
                                   np.var(train_ret) / (np.mean(train_vix**2) + 1e-8) * 0.5,
                                   0.05, 0.05, 0.05, 0.88])

        # Run filter on training to get g[T]
        theta0, theta1, omega_g, alpha, gamma_p, beta_p = a4f_params
        n_train = len(train_ret)
        vix_lag = np.empty(n_train)
        vix_lag[0] = train_vix[0]
        vix_lag[1:] = train_vix[:-1]
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        persist = alpha + gamma_p / 2.0 + beta_p
        eg = omega_g / max(1.0 - persist, 0.01)
        g = eg
        for tt in range(1, n_train):
            u_prev = train_ret[tt-1] / np.sqrt(tau[tt])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g = omega_g + alpha * u_prev**2 + asym + beta_p * g
            g = max(g, 1e-10)
        a4f_g_prev = g
        last_a4f_refit = i

    # 1-step forecast
    theta0, theta1, omega_g, alpha, gamma_p, beta_p = a4f_params
    vix_prev = vix[raw_t - 1]
    tau_now = max(theta0 + theta1 * vix_prev**2, 1e-16)

    r_prev = ret[raw_t - 1]
    u_prev = r_prev / np.sqrt(tau_now)
    asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
    g_now = omega_g + alpha * u_prev**2 + asym + beta_p * a4f_g_prev
    g_now = max(g_now, 1e-10)

    a4f_fcst[i] = tau_now * g_now
    a4f_g_prev = g_now

print(f"  A4f done in {time.time() - START_TIME:.1f}s")

# ============================================================
# SECTION 7: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

# HAR models predict |r|, so convert to variance: σ² = (E[|r|] / sqrt(2/π))²
# Under normality, E[|r|] = σ * sqrt(2/π), so σ = |r| * sqrt(π/2)
# σ² = |r|² * π/2
pi_half = np.pi / 2.0

# Convert HAR forecasts (|r|) to variance forecasts for QLIKE on r²
har_var_fcst = (har_fcst ** 2) * pi_half
har_pd_var_fcst = (har_pd_fcst ** 2) * pi_half
har_pd_lasso_var_fcst = (har_pd_lasso_fcst ** 2) * pi_half

# Realized target for QLIKE: r²
# Get actual r² for OOS dates
r2_oos = np.array([ret[raw_t]**2 for raw_t in raw_oos_indices])

# Floor to avoid division by zero
r2_oos_safe = np.maximum(r2_oos, 1e-16)
har_var_safe = np.maximum(har_var_fcst, 1e-16)
har_pd_var_safe = np.maximum(har_pd_var_fcst, 1e-16)
har_pd_lasso_var_safe = np.maximum(har_pd_lasso_var_fcst, 1e-16)
gjr_safe = np.maximum(gjr_fcst, 1e-16)
a4f_safe = np.maximum(a4f_fcst, 1e-16)

# QLIKE on r²
models = {
    'HAR': har_var_safe,
    'HAR-PD': har_pd_var_safe,
    'HAR-PD-LASSO': har_pd_lasso_var_safe,
    'A4f-N': a4f_safe,
    'GJR-N': gjr_safe,
}

print("\n  Model QLIKE values (lower is better):")
print(f"  {'Model':<15} {'QLIKE':>10} {'Spearman ρ':>12}")
print(f"  {'-'*37}")

qlike_results = {}
spearman_results = {}
for name, fcst in models.items():
    ql = qlike_loss(r2_oos_safe, fcst)
    # Spearman correlation
    rho, p = stats.spearmanr(r2_oos_safe, fcst)
    qlike_results[name] = ql
    spearman_results[name] = (rho, p)
    print(f"  {name:<15} {ql:>10.4f} {rho:>10.4f} (p={p:.2e})")

# Pairwise DM tests
print("\n  Pairwise DM tests (QLIKE on r²):")
print(f"  {'Model A vs B':<30} {'DM stat':>10} {'p-value':>10} {'Winner':>10}")
print(f"  {'-'*60}")

dm_results = {}
pairs = [
    ('HAR-PD', 'HAR'),          # KEY: path features improve HAR?
    ('HAR-PD-LASSO', 'HAR'),    # LASSO selection
    ('HAR-PD', 'HAR-PD-LASSO'), # Full vs LASSO
    ('HAR', 'GJR-N'),           # HAR vs GJR (replicate K530)
    ('HAR-PD', 'GJR-N'),       # HAR-PD vs GJR
    ('HAR-PD', 'A4f-N'),       # HAR-PD vs A4f
    ('HAR', 'A4f-N'),          # HAR vs A4f
    ('A4f-N', 'GJR-N'),       # A4f vs GJR
]

for m1, m2 in pairs:
    loss1 = qlike_loss_array(r2_oos_safe, models[m1])
    loss2 = qlike_loss_array(r2_oos_safe, models[m2])
    dm_stat, p_val = dm_test_func(loss1, loss2)
    winner = m1 if dm_stat < 0 else m2
    sig = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 2.0 else ("*" if abs(dm_stat) > 1.65 else ""))
    label = f"{m1} vs {m2}"
    dm_results[label] = {'dm_stat': dm_stat, 'p_value': p_val, 'winner': winner}
    print(f"  {label:<30} {dm_stat:>10.3f} {p_val:>10.4f} {winner:>8} {sig}")

# HAR-PD feature importance (average |t-stat| of path features over OOS refits)
print("\n  Path feature analysis (last refit OLS coefficients):")
# Do one final OLS on last training window for HAR-PD
last_oos_t = oos_indices[-1]
t_start = max(0, last_oos_t - HAR_WINDOW)
train_data = feat_vals[t_start:last_oos_t]
X_train = train_data[:, all_pd_cols]
y_train = train_data[:, target_idx]
valid = ~np.isnan(y_train)
X_train = X_train[valid]
y_train = y_train[valid]

X_aug = np.column_stack([np.ones(len(y_train)), X_train])
beta_final = np.linalg.lstsq(X_aug, y_train, rcond=None)[0]
y_pred = X_aug @ beta_final
residuals = y_train - y_pred
s2 = np.sum(residuals**2) / (len(y_train) - X_aug.shape[1])
cov_beta = s2 * np.linalg.inv(X_aug.T @ X_aug)
se = np.sqrt(np.diag(cov_beta))
t_stats = beta_final / se

feat_names = ['intercept', 'rv1', 'rv5', 'rv22', 'trend', 'convex', 'mom', 'jump', 'asym', 'vix_gap']
print(f"  {'Feature':<12} {'Coef':>10} {'SE':>10} {'t-stat':>10} {'Sig':>5}")
print(f"  {'-'*47}")
feature_significance = {}
for j, name in enumerate(feat_names):
    sig_marker = "***" if abs(t_stats[j]) > 3.0 else ("**" if abs(t_stats[j]) > 2.0 else ("*" if abs(t_stats[j]) > 1.65 else ""))
    print(f"  {name:<12} {beta_final[j]:>10.6f} {se[j]:>10.6f} {t_stats[j]:>10.3f} {sig_marker:>5}")
    feature_significance[name] = {'coef': float(beta_final[j]), 'se': float(se[j]),
                                   't_stat': float(t_stats[j])}

# ============================================================
# SECTION 8: VISUALIZATION
# ============================================================
print("\n[7] Creating comparison plot...")
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f'{EXPERIMENT_ID}: HAR-PD Path-Dependent Volatility Forecasting', fontsize=14)

    # Plot 1: QLIKE comparison
    ax = axes[0, 0]
    names = list(qlike_results.keys())
    vals = [qlike_results[n] for n in names]
    colors = ['#2196F3' if 'HAR-PD' in n else '#4CAF50' if n == 'HAR' else '#FF9800' if 'A4f' in n else '#9E9E9E' for n in names]
    bars = ax.bar(range(len(names)), vals, color=colors)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, fontsize=9)
    ax.set_ylabel('QLIKE (lower = better)')
    ax.set_title('OOS QLIKE on r²')
    for bar, v in zip(bars, vals):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.001,
                f'{v:.4f}', ha='center', va='bottom', fontsize=8)

    # Plot 2: Spearman correlation
    ax = axes[0, 1]
    rhos = [spearman_results[n][0] for n in names]
    bars = ax.bar(range(len(names)), rhos, color=colors)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, rotation=30, fontsize=9)
    ax.set_ylabel('Spearman ρ')
    ax.set_title('OOS Rank Correlation with r²')
    for bar, v in zip(bars, rhos):
        ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.001,
                f'{v:.4f}', ha='center', va='bottom', fontsize=8)

    # Plot 3: Rolling QLIKE (250-day window)
    ax = axes[1, 0]
    roll_window = 250
    for name, fcst in models.items():
        loss_arr = qlike_loss_array(r2_oos_safe, fcst)
        rolling_ql = pd.Series(loss_arr).rolling(roll_window).mean().values
        ax.plot(oos_dates, rolling_ql, label=name, alpha=0.8)
    ax.set_ylabel('Rolling QLIKE (250d)')
    ax.set_title('Rolling QLIKE Over Time')
    ax.legend(fontsize=8)
    ax.tick_params(axis='x', rotation=30)

    # Plot 4: Path feature t-stats
    ax = axes[1, 1]
    path_feat_names = ['trend', 'convex', 'mom', 'jump', 'asym', 'vix_gap']
    path_tstats = [feature_significance[n]['t_stat'] for n in path_feat_names]
    pcolors = ['#4CAF50' if abs(t) > 3.0 else '#FF9800' if abs(t) > 2.0 else '#9E9E9E' for t in path_tstats]
    ax.barh(range(len(path_feat_names)), path_tstats, color=pcolors)
    ax.set_yticks(range(len(path_feat_names)))
    ax.set_yticklabels(path_feat_names)
    ax.axvline(x=3.0, color='red', linestyle='--', alpha=0.5, label='Harvey t=3.0')
    ax.axvline(x=-3.0, color='red', linestyle='--', alpha=0.5)
    ax.axvline(x=0, color='black', linestyle='-', alpha=0.3)
    ax.set_xlabel('t-statistic')
    ax.set_title('Path Feature Significance (last refit)')
    ax.legend(fontsize=8)

    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Plot saved: {PLOT_PATH}")
except Exception as e:
    print(f"  Plot failed: {e}")

# ============================================================
# SECTION 9: RESULTS SUMMARY
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n[8] Summary (elapsed: {elapsed:.1f}s)")

# Key result: HAR-PD vs HAR
har_pd_vs_har = dm_results.get('HAR-PD vs HAR', {})
har_pd_lasso_vs_har = dm_results.get('HAR-PD-LASSO vs HAR', {})
har_vs_gjr = dm_results.get('HAR vs GJR-N', {})
har_pd_vs_a4f = dm_results.get('HAR-PD vs A4f-N', {})

print(f"\n  KEY RESULTS:")
print(f"  HAR-PD vs HAR:       DM={har_pd_vs_har.get('dm_stat', 'N/A'):.3f}, "
      f"{'SIGNIFICANT' if abs(har_pd_vs_har.get('dm_stat', 0)) > 3.0 else 'NOT significant'}")
print(f"  HAR-PD-LASSO vs HAR: DM={har_pd_lasso_vs_har.get('dm_stat', 'N/A'):.3f}, "
      f"{'SIGNIFICANT' if abs(har_pd_lasso_vs_har.get('dm_stat', 0)) > 3.0 else 'NOT significant'}")
print(f"  HAR vs GJR:          DM={har_vs_gjr.get('dm_stat', 'N/A'):.3f}, "
      f"{'SIGNIFICANT' if abs(har_vs_gjr.get('dm_stat', 0)) > 3.0 else 'NOT significant'}")
print(f"  HAR-PD vs A4f:       DM={har_pd_vs_a4f.get('dm_stat', 'N/A'):.3f}, "
      f"{'SIGNIFICANT' if abs(har_pd_vs_a4f.get('dm_stat', 0)) > 3.0 else 'NOT significant'}")

# Determine if path features matter
path_sig = abs(har_pd_vs_har.get('dm_stat', 0)) > 3.0 and har_pd_vs_har.get('dm_stat', 0) < 0
conclusion = (
    "HAR-PD SIGNIFICANTLY improves over HAR — path features add predictive value at daily frequency"
    if path_sig else
    "HAR-PD does NOT significantly improve HAR (Harvey t>3.0) — path features redundant with |r| proxy at daily frequency"
)

# Significant path features
sig_features = [n for n in path_feat_names if abs(feature_significance[n]['t_stat']) > 3.0]

print(f"\n  CONCLUSION: {conclusion}")
print(f"  Significant path features (|t|>3): {sig_features if sig_features else 'None'}")

# Save results
results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'HAR-PD (Path-Dependent) Volatility Forecasting',
    'proposer': 'Claude',
    'executor': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': n_total,
    'n_oos': n_oos_har,
    'oos_start': OOS_START,
    'har_window': HAR_WINDOW,
    'garch_window': GARCH_WINDOW,
    'refit_every': REFIT_EVERY,
    'references': [
        'arXiv:2503.00851 - Path-dependent HAR',
        'Corsi (2009, JFE) - HAR-RV model',
        'Patton (2011, J Econometrics) - QLIKE loss',
        'Harvey et al. (2016) - t > 3.0 threshold',
        'K530 - HAR-ABS vs GJR baseline',
        'K988 - MF-GJR-X A4f specification',
    ],
    'models': list(models.keys()),
    'qlike_results': {k: float(v) for k, v in qlike_results.items()},
    'spearman_results': {k: {'rho': float(v[0]), 'p_value': float(v[1])} for k, v in spearman_results.items()},
    'dm_tests': {k: {kk: float(vv) if isinstance(vv, (int, float, np.floating)) else str(vv)
                      for kk, vv in v.items()}
                 for k, v in dm_results.items()},
    'path_feature_significance': {k: {kk: float(vv) for kk, vv in v.items()}
                                   for k, v in feature_significance.items()},
    'significant_path_features': sig_features,
    'conclusion': conclusion,
    'elapsed_seconds': round(elapsed, 1),
    'seed': 42,
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)
print(f"\n  Results saved: {RESULTS_PATH}")
print(f"\n{'='*70}")
print(f"  {EXPERIMENT_ID} COMPLETE")
print(f"{'='*70}")
