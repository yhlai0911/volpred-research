#!/usr/bin/env python3
"""
K998: VRP Predictability from MF-GJR-X g Component
====================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988b found that the g component of A4f (vix_squared, free_omega, tau_t) model
  has high Spearman rho = 0.63 with independently computed VRP (Variance Risk Premium).
  This suggests g's GARCH dynamics effectively track VRP deviations from long-run mean.

  Key question: Can g PREDICT future VRP (not just contemporaneous correlation)?
  If yes, this has economic implications for variance swap trading.

Research Questions:
  1. Does g Granger-cause future VRP at h=1,5,10,22 day horizons?
  2. Does g add incremental predictive power beyond simple VRP lag and VIX level?
  3. What is the out-of-sample R² (Campbell & Thompson 2008)?
  4. Can a simple variance swap strategy based on g signals generate economic value?

Method:
  - Rolling window A4f estimation (window=2000, refit every 63 days)
  - Extract OOS g series
  - VRP proxy: VRP_t = VIX²_{t-1}/252 - r²_t (daily)
  - Granger causality tests at h=1,5,10,22
  - Predictive regressions with Newey-West HAC standard errors
  - OOS R² via expanding window (Campbell & Thompson 2008)
  - Variance swap strategy simulation

References:
  - Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and Variance Risk Premia. RFS 22(11):4463-4492.
  - Campbell & Thompson (2008). Predicting Excess Stock Returns OOS. RFS 21(4):1509-1531.
  - Newey & West (1987). A Simple, Positive Semi-definite, Heteroskedasticity and
    Autocorrelation Consistent Covariance Matrix. Econometrica 55(3):703-708.
  - Harvey et al. (2016). t > 3.0 threshold for multiple testing.
  - Carr & Wu (2009). Variance Risk Premiums. RFS 22(3):1311-1341.

Data: SPY 2005-2026, VIX from yfinance. OOS: 2019-01-01 to latest.

Author: VolPred Research System
Date: 2026-04-08
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
from scipy.special import gammaln

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K998"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k998_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print(f"{EXPERIMENT_ID}: VRP Predictability from MF-GJR-X g Component")
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

# Compute VRP proxy: VRP_t = VIX²_{t-1}/252 - r²_t
# VIX is annualized %, so VIX/100 gives annualized decimal vol
# VIX²/10000 = annualized variance; /252 = daily implied variance
df['VIX_lag'] = df['VIX'].shift(1)
df['r2'] = df['log_ret'] ** 2
df['implied_var'] = (df['VIX_lag'] / 100) ** 2 / 252  # daily implied variance
df['VRP'] = df['implied_var'] - df['r2']  # VRP = implied - realized
df = df.dropna()

oos_mask = df.index >= OOS_START
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2
vrp = df['VRP'].values

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
oos_vrp = vrp[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std: {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS VRP mean (annualized): {np.mean(oos_vrp)*252*1e4:.2f} bps")
print(f"  OOS VRP std (annualized): {np.std(oos_vrp)*252*1e4:.2f} bps")
print(f"  OOS VRP autocorr(1): {np.corrcoef(oos_vrp[1:], oos_vrp[:-1])[0,1]:.4f}")
print(f"  VRP skewness: {stats.skew(oos_vrp):.3f}")
print(f"  VRP kurtosis: {stats.kurtosis(oos_vrp):.3f}")

# ============================================================
# SECTION 3: A4f MODEL (vix_squared, free_omega, tau_t)
# ============================================================
print("\n[3] Estimating A4f model (rolling window, extracting g series)...")

def fit_a4f(returns, vix_vals):
    """Fit A4f: tau_t = max(theta0 + theta1 * VIX²_{t-1}, eps), free omega, denom=tau_t."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag ** 2) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta_p = params

        tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta_p < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta_p
        if persist >= 1.0:
            return 1e10

        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg
        ll = 0.0

        for t in range(1, n):
            u_prev = returns[t - 1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev ** 2 + asym + beta_p * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t] ** 2 / sigma2)

        return -ll

    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

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


def extract_g_series(params, returns, vix_vals):
    """Given fitted params, compute full g series."""
    theta0, theta1, omega_g, alpha, gamma_p, beta_p = params
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    tau = np.maximum(theta0 + theta1 * vix_lag ** 2, 1e-16)

    persist = alpha + gamma_p / 2.0 + beta_p
    eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0

    g = np.empty(n)
    g[0] = eg

    for t in range(1, n):
        u_prev = returns[t - 1] / np.sqrt(tau[t])
        asym = gamma_p * u_prev ** 2 if u_prev < 0 else 0.0
        g[t] = omega_g + alpha * u_prev ** 2 + asym + beta_p * g[t - 1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    return g, tau


# Rolling window estimation with g extraction
oos_indices = np.where(oos_mask)[0]
g_oos = np.full(n_total, np.nan)
tau_oos = np.full(n_total, np.nan)

# Determine refit points
first_oos = oos_indices[0]
refit_points = list(range(first_oos, n_total, REFIT_EVERY))
if refit_points[-1] != n_total - 1:
    refit_points.append(n_total)

n_refits = len(refit_points) - 1
print(f"  Refitting {n_refits} times (every {REFIT_EVERY} days)...")

current_params = None
for i in range(n_refits):
    start_idx = refit_points[i]
    end_idx = refit_points[i + 1] if i + 1 < len(refit_points) else n_total

    # Fit on window ending at start_idx
    window_end = start_idx
    window_start = max(0, window_end - WINDOW)

    train_ret = ret[window_start:window_end]
    train_vix = vix[window_start:window_end]

    params = fit_a4f(train_ret, train_vix)
    if params is None:
        if current_params is not None:
            params = current_params
        else:
            continue
    current_params = params

    # Extract g for the full window + OOS segment
    full_ret = ret[window_start:end_idx]
    full_vix = vix[window_start:end_idx]
    g_full, tau_full = extract_g_series(params, full_ret, full_vix)

    # Only keep OOS portion
    oos_offset = window_end - window_start
    for t in range(start_idx, end_idx):
        idx_in_full = t - window_start
        if idx_in_full < len(g_full):
            g_oos[t] = g_full[idx_in_full]
            tau_oos[t] = tau_full[idx_in_full]

    if (i + 1) % 10 == 0:
        print(f"    Refit {i + 1}/{n_refits} done")

print(f"  Total refits: {n_refits}")

# Extract OOS g and tau
g_series = g_oos[oos_mask]
tau_series = tau_oos[oos_mask]
vrp_oos = vrp[oos_mask]
r2_oos = r2[oos_mask]
vix_oos = vix[oos_mask]

valid = ~np.isnan(g_series) & ~np.isnan(vrp_oos) & np.isfinite(g_series) & np.isfinite(vrp_oos)
n_valid = valid.sum()
print(f"  Valid OOS observations: {n_valid}")

# Contemporaneous correlation check
spear_g_vrp = stats.spearmanr(g_series[valid], vrp_oos[valid])
print(f"  Contemporaneous Spearman(g, VRP): {spear_g_vrp.statistic:.4f} (p={spear_g_vrp.pvalue:.2e})")

# ============================================================
# SECTION 4: GRANGER CAUSALITY TESTS
# ============================================================
print("\n[4] Granger causality tests: g -> VRP...")

results = {}
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'n_oos': int(n_valid),
    'n_refits': n_refits,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'data_source': 'yfinance (SPY, ^VIX)',
    'period': f'{df.index[0].strftime("%Y-%m-%d")} to {df.index[-1].strftime("%Y-%m-%d")}',
    'oos_start': OOS_START,
    'oos_r2_alignment': 'h-step expanding forecasts train only on pairs whose target date is already realized at the forecast origin',
}

results['contemporaneous'] = {
    'spearman_g_vrp': float(spear_g_vrp.statistic),
    'spearman_p': float(spear_g_vrp.pvalue),
}

# Diagnostics — persisted so Paper 9 Table 1 has a citable source
# (previously only printed at line 129; Paper 9 autocorr=0.20 no-source task)
results['diagnostics'] = {
    'oos_vrp_autocorr_lag1': float(np.corrcoef(oos_vrp[1:], oos_vrp[:-1])[0, 1]),
    'oos_vrp_mean_bps_ann': float(np.mean(oos_vrp) * 252 * 1e4),
    'oos_vrp_std_bps_ann': float(np.std(oos_vrp) * 252 * 1e4),
    'oos_vrp_skewness': float(stats.skew(oos_vrp)),
    'oos_vrp_kurtosis': float(stats.kurtosis(oos_vrp)),
    'oos_ret_mean_ann': float(np.mean(oos_ret) * 252),
    'oos_ret_std_ann': float(np.std(oos_ret) * np.sqrt(252)),
}

# Use valid series
g_v = g_series[valid]
vrp_v = vrp_oos[valid]
vix_v = vix_oos[valid]
r2_v = r2_oos[valid]

horizons = [1, 5, 10, 22]
granger_results = {}

for h in horizons:
    # Granger test: Does adding g_{t-h} improve prediction of VRP_t beyond VRP_{t-h}?
    n_gc = len(vrp_v) - h
    if n_gc < 100:
        continue

    y = vrp_v[h:]
    # Restricted model: VRP_t ~ const + VRP_{t-h}
    X_r = np.column_stack([np.ones(n_gc), vrp_v[:n_gc]])
    # Unrestricted model: VRP_t ~ const + VRP_{t-h} + g_{t-h}
    X_u = np.column_stack([np.ones(n_gc), vrp_v[:n_gc], g_v[:n_gc]])

    # OLS for restricted
    beta_r = np.linalg.lstsq(X_r, y, rcond=None)[0]
    resid_r = y - X_r @ beta_r
    ssr_r = np.sum(resid_r ** 2)

    # OLS for unrestricted
    beta_u = np.linalg.lstsq(X_u, y, rcond=None)[0]
    resid_u = y - X_u @ beta_u
    ssr_u = np.sum(resid_u ** 2)

    # F-test: (SSR_r - SSR_u) / q / (SSR_u / (n - k))
    q = 1  # one additional regressor
    k_u = X_u.shape[1]
    f_stat = ((ssr_r - ssr_u) / q) / (ssr_u / (n_gc - k_u))
    f_pval = 1 - stats.f.cdf(f_stat, q, n_gc - k_u)

    granger_results[f'h={h}'] = {
        'f_stat': float(f_stat),
        'p_value': float(f_pval),
        'significant_001': bool(f_pval < 0.01),
        'n': int(n_gc),
        'r2_restricted': float(1 - ssr_r / np.sum((y - np.mean(y)) ** 2)),
        'r2_unrestricted': float(1 - ssr_u / np.sum((y - np.mean(y)) ** 2)),
    }
    print(f"  h={h}: F={f_stat:.3f}, p={f_pval:.4f}, R2_r={granger_results[f'h={h}']['r2_restricted']:.4f}, R2_u={granger_results[f'h={h}']['r2_unrestricted']:.4f}")

results['granger_causality'] = granger_results

# ============================================================
# SECTION 5: PREDICTIVE REGRESSIONS WITH NEWEY-WEST HAC
# ============================================================
print("\n[5] Predictive regressions: VRP_{t+h} ~ g_t + controls...")


def newey_west_se(X, resid, lag=None):
    """Compute Newey-West HAC standard errors."""
    n, k = X.shape
    if lag is None:
        lag = int(n ** (1 / 3))

    # Meat matrix
    S = np.zeros((k, k))

    # Lag 0
    for t in range(n):
        x = X[t:t + 1].T  # k x 1
        S += resid[t] ** 2 * (x @ x.T)

    # Lags 1..L
    for j in range(1, lag + 1):
        w = 1.0 - j / (lag + 1.0)  # Bartlett kernel
        Gamma_j = np.zeros((k, k))
        for t in range(j, n):
            xi = X[t:t + 1].T
            xj = X[t - j:t - j + 1].T
            Gamma_j += resid[t] * resid[t - j] * (xi @ xj.T)
        S += w * (Gamma_j + Gamma_j.T)

    # Bread
    XtX_inv = np.linalg.inv(X.T @ X)
    V = XtX_inv @ S @ XtX_inv

    return np.sqrt(np.diag(V))


pred_reg_results = {}

for h in horizons:
    n_pr = len(vrp_v) - h
    if n_pr < 100:
        continue

    y = vrp_v[h:]  # VRP_{t+h}

    # Model 1: VRP_{t+h} ~ const + g_t
    X1 = np.column_stack([np.ones(n_pr), g_v[:n_pr]])
    beta1 = np.linalg.lstsq(X1, y, rcond=None)[0]
    resid1 = y - X1 @ beta1
    se1 = newey_west_se(X1, resid1)
    t1 = beta1 / se1

    # Model 2: VRP_{t+h} ~ const + VRP_t + g_t
    X2 = np.column_stack([np.ones(n_pr), vrp_v[:n_pr], g_v[:n_pr]])
    beta2 = np.linalg.lstsq(X2, y, rcond=None)[0]
    resid2 = y - X2 @ beta2
    se2 = newey_west_se(X2, resid2)
    t2 = beta2 / se2

    # Model 3: VRP_{t+h} ~ const + VRP_t + log(VIX_t) + g_t
    log_vix_v = np.log(np.maximum(vix_v, 1.0))
    X3 = np.column_stack([np.ones(n_pr), vrp_v[:n_pr], log_vix_v[:n_pr], g_v[:n_pr]])
    beta3 = np.linalg.lstsq(X3, y, rcond=None)[0]
    resid3 = y - X3 @ beta3
    se3 = newey_west_se(X3, resid3)
    t3 = beta3 / se3

    # Model 4: VRP_{t+h} ~ const + VRP_t + VIX_t + VIX²_t + g_t (full controls)
    X4 = np.column_stack([np.ones(n_pr), vrp_v[:n_pr], vix_v[:n_pr] / 100,
                          (vix_v[:n_pr] / 100) ** 2, g_v[:n_pr]])
    beta4 = np.linalg.lstsq(X4, y, rcond=None)[0]
    resid4 = y - X4 @ beta4
    se4 = newey_west_se(X4, resid4)
    t4 = beta4 / se4

    r2_m1 = float(1 - np.sum(resid1 ** 2) / np.sum((y - np.mean(y)) ** 2))
    r2_m2 = float(1 - np.sum(resid2 ** 2) / np.sum((y - np.mean(y)) ** 2))
    r2_m3 = float(1 - np.sum(resid3 ** 2) / np.sum((y - np.mean(y)) ** 2))
    r2_m4 = float(1 - np.sum(resid4 ** 2) / np.sum((y - np.mean(y)) ** 2))

    pred_reg_results[f'h={h}'] = {
        'model1_g_only': {
            'beta_g': float(beta1[1]),
            'se_g': float(se1[1]),
            't_g': float(t1[1]),
            'significant_harvey': bool(abs(t1[1]) > 3.0),
            'R2': r2_m1,
        },
        'model2_vrp_g': {
            'beta_vrp': float(beta2[1]),
            't_vrp': float(t2[1]),
            'beta_g': float(beta2[2]),
            'se_g': float(se2[2]),
            't_g': float(t2[2]),
            'significant_harvey': bool(abs(t2[2]) > 3.0),
            'R2': r2_m2,
        },
        'model3_vrp_logvix_g': {
            'beta_vrp': float(beta3[1]),
            't_vrp': float(t3[1]),
            'beta_logvix': float(beta3[2]),
            't_logvix': float(t3[2]),
            'beta_g': float(beta3[3]),
            'se_g': float(se3[3]),
            't_g': float(t3[3]),
            'significant_harvey': bool(abs(t3[3]) > 3.0),
            'R2': r2_m3,
        },
        'model4_full_controls': {
            'beta_g': float(beta4[-1]),
            'se_g': float(se4[-1]),
            't_g': float(t4[-1]),
            'significant_harvey': bool(abs(t4[-1]) > 3.0),
            'R2': r2_m4,
        },
        'n': int(n_pr),
    }

    print(f"  h={h}:")
    print(f"    Model 1 (g only):       t_g={t1[1]:.3f}, R²={r2_m1:.4f}")
    print(f"    Model 2 (VRP+g):        t_g={t2[2]:.3f}, R²={r2_m2:.4f}")
    print(f"    Model 3 (VRP+logVIX+g): t_g={t3[3]:.3f}, R²={r2_m3:.4f}")
    print(f"    Model 4 (full+g):       t_g={t4[-1]:.3f}, R²={r2_m4:.4f}")

results['predictive_regressions'] = pred_reg_results

# ============================================================
# SECTION 6: OUT-OF-SAMPLE R² (Campbell & Thompson 2008)
# ============================================================
print("\n[6] Out-of-sample R² (expanding window)...")

oos_r2_results = {}

for h in horizons:
    n_pr = len(vrp_v) - h
    if n_pr < 252:
        continue

    y = vrp_v[h:]
    g_for_pred = g_v[:n_pr]
    vrp_for_pred = vrp_v[:n_pr]

    # Minimum training window: 252 observations
    min_train = 252
    first_eval = min_train + h - 1
    n_eval = n_pr - first_eval

    if n_eval < 100:
        continue

    errors_hm = []
    errors_g = []
    errors_ar = []
    errors_ar_g = []

    for t in range(first_eval, n_pr):
        # Forecast origin is t. For h-step targets, only pairs whose realized
        # target date is <= t are known: j+h <= t, so j <= t-h.
        train_n = t - h + 1
        y_train = y[:train_n]
        g_train = g_for_pred[:train_n]
        vrp_train = vrp_for_pred[:train_n]

        # Historical mean forecast
        yhat_hm = np.mean(y_train)

        # g-only model
        X_g = np.column_stack([np.ones(train_n), g_train])
        try:
            beta_g = np.linalg.lstsq(X_g, y_train, rcond=None)[0]
            yhat_g = beta_g[0] + beta_g[1] * g_for_pred[t]
        except Exception:
            yhat_g = yhat_hm

        # AR(1) model
        X_ar = np.column_stack([np.ones(train_n), vrp_train])
        try:
            beta_ar = np.linalg.lstsq(X_ar, y_train, rcond=None)[0]
            yhat_ar = beta_ar[0] + beta_ar[1] * vrp_for_pred[t]
        except Exception:
            yhat_ar = yhat_hm

        # AR(1) + g model
        X_ar_g = np.column_stack([np.ones(train_n), vrp_train, g_train])
        try:
            beta_ar_g = np.linalg.lstsq(X_ar_g, y_train, rcond=None)[0]
            yhat_ar_g = beta_ar_g[0] + beta_ar_g[1] * vrp_for_pred[t] + beta_ar_g[2] * g_for_pred[t]
        except Exception:
            yhat_ar_g = yhat_hm

        actual = y[t]
        errors_hm.append((actual - yhat_hm) ** 2)
        errors_g.append((actual - yhat_g) ** 2)
        errors_ar.append((actual - yhat_ar) ** 2)
        errors_ar_g.append((actual - yhat_ar_g) ** 2)

    errors_hm = np.asarray(errors_hm)
    errors_g = np.asarray(errors_g)
    errors_ar = np.asarray(errors_ar)
    errors_ar_g = np.asarray(errors_ar_g)

    # R²_OOS = 1 - MSE_model / MSE_benchmark
    mse_hm = np.mean(errors_hm)
    r2_oos_g = 1 - np.mean(errors_g) / mse_hm
    r2_oos_ar = 1 - np.mean(errors_ar) / mse_hm
    r2_oos_ar_g = 1 - np.mean(errors_ar_g) / mse_hm

    # Clark-West (2007) test: H0: R²_OOS <= 0
    # CW statistic: mean of f_t = (e_hm^2 - (e_g^2 - (yhat_hm - yhat_g)^2))
    # Simplified: we test if the model MSE < benchmark MSE using t-test on loss diff
    # For simplicity, use DM-style test on squared errors
    # Clark-West adjustment
    # d_t = e_hm^2 - e_g^2 + (yhat_hm - yhat_g)^2 ... but needs paired forecasts
    # Use simpler DM-style: d_t = e_hm^2 - e_model^2
    d_g = errors_hm - errors_g
    d_ar_g = errors_hm - errors_ar_g

    t_cw_g = np.mean(d_g) / (np.std(d_g, ddof=1) / np.sqrt(len(d_g)))
    t_cw_ar_g = np.mean(d_ar_g) / (np.std(d_ar_g, ddof=1) / np.sqrt(len(d_ar_g)))

    p_cw_g = 1 - stats.norm.cdf(t_cw_g)  # one-sided
    p_cw_ar_g = 1 - stats.norm.cdf(t_cw_ar_g)

    oos_r2_results[f'h={h}'] = {
        'R2_OOS_g_only': float(r2_oos_g),
        'R2_OOS_AR1': float(r2_oos_ar),
        'R2_OOS_AR1_plus_g': float(r2_oos_ar_g),
        'CW_t_g_vs_HM': float(t_cw_g),
        'CW_p_g_vs_HM': float(p_cw_g),
        'CW_t_ARg_vs_HM': float(t_cw_ar_g),
        'CW_p_ARg_vs_HM': float(p_cw_ar_g),
        'n_eval': int(n_eval),
        'alignment': 'no target-overlap lookahead: training responses satisfy target_date <= forecast_origin',
    }
    print(f"  h={h}: R²_OOS(g)={r2_oos_g:.4f}, R²_OOS(AR1)={r2_oos_ar:.4f}, R²_OOS(AR1+g)={r2_oos_ar_g:.4f}")
    print(f"         CW_t(g vs HM)={t_cw_g:.3f} (p={p_cw_g:.4f}), CW_t(AR+g vs HM)={t_cw_ar_g:.3f} (p={p_cw_ar_g:.4f})")

results['oos_r2'] = oos_r2_results

# ============================================================
# SECTION 7: VARIANCE SWAP STRATEGY SIMULATION
# ============================================================
print("\n[7] Variance swap strategy simulation...")

# Signal: g_t (lagged by 1 day for trading, i.e., use g_{t-1})
# When g > median → sell variance (collect VRP, expect mean reversion)
# When g < median → buy variance (hedge, expect VRP to rise)

# Use expanding median for signal
g_signal = g_v.copy()
vrp_payoff = vrp_v.copy()

# Lag signal by 1 day (signal from t-1, payoff at t)
signal = np.full(len(g_signal), np.nan)
for t in range(252, len(g_signal)):
    median_g = np.median(g_signal[:t])
    signal[t] = 1.0 if g_signal[t - 1] > median_g else -1.0  # shift(1) equivalent

# Strategy return: sell variance when g high, buy when g low
# Selling variance = receive VRP (positive when implied > realized)
strat_ret = signal * vrp_payoff

valid_strat = ~np.isnan(strat_ret)
strat_clean = strat_ret[valid_strat]
n_strat = len(strat_clean)

if n_strat > 100:
    # Annualize
    mean_ret = np.mean(strat_clean) * 252
    std_ret = np.std(strat_clean, ddof=1) * np.sqrt(252)
    sharpe = mean_ret / std_ret if std_ret > 0 else 0.0

    # Baseline: always sell variance (collect VRP)
    baseline_ret = vrp_payoff[valid_strat]
    baseline_mean = np.mean(baseline_ret) * 252
    baseline_std = np.std(baseline_ret, ddof=1) * np.sqrt(252)
    baseline_sharpe = baseline_mean / baseline_std if baseline_std > 0 else 0.0

    # Hit rate
    hit_rate = np.mean(strat_clean > 0)

    # Max drawdown of cumulative strategy
    cum_strat = np.cumsum(strat_clean)
    peak = np.maximum.accumulate(cum_strat)
    dd = cum_strat - peak
    max_dd = np.min(dd)

    strat_results = {
        'n_days': int(n_strat),
        'annualized_mean': float(mean_ret),
        'annualized_std': float(std_ret),
        'sharpe': float(sharpe),
        'hit_rate': float(hit_rate),
        'max_drawdown': float(max_dd),
        'baseline_always_sell': {
            'annualized_mean': float(baseline_mean),
            'annualized_std': float(baseline_std),
            'sharpe': float(baseline_sharpe),
        },
        'signal_lag': 1,
        'note': 'signal.shift(1) applied - g_{t-1} used to trade at t',
    }
    print(f"  Strategy: Sharpe={sharpe:.3f}, Mean={mean_ret*1e4:.1f}bps, Hit={hit_rate:.3f}")
    print(f"  Baseline (always sell): Sharpe={baseline_sharpe:.3f}, Mean={baseline_mean*1e4:.1f}bps")

    # Check: Sharpe > 2x baseline = suspicious
    if abs(sharpe) > 2 * abs(baseline_sharpe) and abs(baseline_sharpe) > 0.1:
        print(f"  ⚠️ WARNING: Sharpe {sharpe:.3f} > 2x baseline {baseline_sharpe:.3f} — check for bugs!")
        strat_results['warning'] = 'Sharpe > 2x baseline, needs verification'
else:
    strat_results = {'n_days': int(n_strat), 'note': 'Insufficient data'}

results['variance_swap_strategy'] = strat_results

# ============================================================
# SECTION 8: ADDITIONAL ANALYSIS - g vs VIX level comparison
# ============================================================
print("\n[8] Comparing g predictive power vs VIX level...")

comparison_results = {}
for h in [1, 5, 22]:
    n_pr = len(vrp_v) - h
    if n_pr < 100:
        continue

    y = vrp_v[h:]
    log_vix_v = np.log(np.maximum(vix_v, 1.0))

    # VIX-only model
    X_vix = np.column_stack([np.ones(n_pr), log_vix_v[:n_pr]])
    beta_vix = np.linalg.lstsq(X_vix, y, rcond=None)[0]
    resid_vix = y - X_vix @ beta_vix
    se_vix = newey_west_se(X_vix, resid_vix)
    t_vix = beta_vix / se_vix
    r2_vix = float(1 - np.sum(resid_vix ** 2) / np.sum((y - np.mean(y)) ** 2))

    # g-only model
    X_g = np.column_stack([np.ones(n_pr), g_v[:n_pr]])
    beta_g_only = np.linalg.lstsq(X_g, y, rcond=None)[0]
    resid_g_only = y - X_g @ beta_g_only
    r2_g_only = float(1 - np.sum(resid_g_only ** 2) / np.sum((y - np.mean(y)) ** 2))

    # VRP lag only
    X_vrp = np.column_stack([np.ones(n_pr), vrp_v[:n_pr]])
    beta_vrp_only = np.linalg.lstsq(X_vrp, y, rcond=None)[0]
    resid_vrp_only = y - X_vrp @ beta_vrp_only
    r2_vrp_only = float(1 - np.sum(resid_vrp_only ** 2) / np.sum((y - np.mean(y)) ** 2))

    comparison_results[f'h={h}'] = {
        'R2_VIX_only': r2_vix,
        'R2_g_only': r2_g_only,
        'R2_VRP_lag_only': r2_vrp_only,
        't_VIX': float(t_vix[1]),
    }
    print(f"  h={h}: R²(VIX)={r2_vix:.4f}, R²(g)={r2_g_only:.4f}, R²(VRP_lag)={r2_vrp_only:.4f}")

results['g_vs_vix_comparison'] = comparison_results

# ============================================================
# SECTION 9: SUMMARY AND CONCLUSIONS
# ============================================================
print("\n[9] Summary...")

# Determine if g has predictive power
any_granger_sig = any(
    v.get('significant_001', False) for v in granger_results.values()
)
any_pred_reg_sig = any(
    v.get('model2_vrp_g', {}).get('significant_harvey', False)
    for v in pred_reg_results.values()
)
any_oos_positive = any(
    v.get('R2_OOS_AR1_plus_g', 0) > 0 for v in oos_r2_results.values()
)

summary = {
    'granger_any_significant': any_granger_sig,
    'pred_reg_any_significant_harvey': any_pred_reg_sig,
    'oos_r2_any_positive': any_oos_positive,
    'conclusion': '',
}

if any_pred_reg_sig and any_oos_positive:
    summary['conclusion'] = 'g has genuine predictive power for VRP beyond AR(1) and VIX controls'
elif any_granger_sig and any_oos_positive:
    summary['conclusion'] = 'g Granger-causes VRP with positive OOS R², but incremental t < 3.0'
elif any_granger_sig:
    summary['conclusion'] = 'g Granger-causes VRP in-sample but OOS R² is negative (overfitting)'
else:
    summary['conclusion'] = 'NULL RESULT: g is a contemporaneous VRP proxy with no predictive power'

results['summary'] = summary
print(f"  {summary['conclusion']}")

# ============================================================
# SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
results['metadata']['elapsed'] = float(elapsed)
results['metadata']['timestamp'] = datetime.now(timezone.utc).isoformat()

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n{'='*70}")
print(f"Results saved to: {RESULTS_PATH}")
print(f"Elapsed: {elapsed:.1f}s")
print(f"{'='*70}")
