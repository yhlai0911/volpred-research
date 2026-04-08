#!/usr/bin/env python3
"""
K936: Time-Varying Hurst Exponent via Rolling Estimation
=========================================================
[提出: Claude, 執行: Claude]

Problem:
  K529 used a fixed Hurst exponent (H=0.1) for rough volatility. The Rough
  Volatility literature (Gatheral, Jaisson & Rosenbaum 2018) establishes that
  H is substantially below 0.5 for financial assets. But H may vary over time
  with market conditions. This experiment tests whether a time-varying H(t)
  estimated via rolling R/S analysis and rolling variogram methods contains
  predictive information for volatility beyond what VIX already captures.

Models:
  M1: GARCH(1,1) — baseline
  M2: GJR-GARCH(1,1) — standard asymmetric
  M3: MF-GJR(VIX) — current best (K889 confirmed)
  M4: MF-GJR(H) — Hurst only: tau_t = exp(theta_0 + theta_2 * H_{t-1})
  M5: MF-GJR(VIX, H) — both: tau_t = exp(theta_0 + theta_1*log(VIX_{t-1}) + theta_2*H_{t-1})

Key Question:
  Does H(t) contain incremental information beyond VIX for vol forecasting?
  - If M5 >> M3: H(t) adds value beyond VIX
  - If M4 >> M2 but M4 ≈ M3: Hurst info subsumed by VIX
  - If M4 ≈ M2: daily-frequency Hurst has no predictive power

Hurst Estimation Methods:
  1. R/S Analysis (classical, rolling window 63d)
  2. Variogram / Detrended Fluctuation Analysis (DFA, rolling window 63d)

Data:
  - Asset: SPY (2006-01-01 to 2026-04-01)
  - OOS: 2016-01-01 to latest
  - VIX from yfinance (^VIX)
  - Window: 2000

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - DM tests with Harvey (2016) |t| > 3.0
  - Spearman rank correlation

Error Log rules:
  - DM test: use volpred.stats.model_evaluation (not self-written)
  - GARCH OOS: recursive h[t] = f(h[t-1], r^2[t-1]), no stale variance
  - Fixed seed: np.random.seed(42)
  - Sharpe > 2x baseline = almost certainly a bug

References:
  - Gatheral, Jaisson & Rosenbaum (2018). Volatility is rough. QF 18(6):933-949.
  - arXiv:2509.05820: EWMA-driven time-varying H in rBergomi
  - Frontiers Applied Math 2025: Adaptive fractal dynamics, time-varying H
  - Patton (2011). J Econometrics 160:246-256.
  - Harvey et al. (2016). JBES 34:92-104.
  - Engle, Ghysels & Sohn (2013). RES 95(3):776-797.

Author: VolPred Research System
Date: 2026-04-06
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
from scipy.stats import norm
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K936"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k936_results.json')

# Data parameters
DATA_START = '2005-01-01'
DATA_END = '2026-04-06'
OOS_START = '2016-01-01'
WINDOW = 2000
REFIT_EVERY = 63
HURST_WINDOW_RS = 63      # Rolling R/S window (1 quarter)
HURST_WINDOW_VAR = 63     # Rolling variogram window
DFA_SCALES = [4, 8, 16, 32]  # DFA scales for Hurst estimation

print("=" * 70)
print(f"{EXPERIMENT_ID}: Time-Varying Hurst Exponent — Predictive Power Test")
print("  Does roughness of volatility predict future vol beyond VIX?")
print("=" * 70)


# ============================================================
# SECTION 1: HURST EXPONENT ESTIMATION
# ============================================================
print("\n[1] Hurst exponent estimation methods...")


def hurst_rs(returns, window=63):
    """
    Rolling R/S (Rescaled Range) analysis for Hurst exponent.

    For each rolling window of absolute returns (proxy for vol process):
    1. Compute R = max(cumulative deviation) - min(cumulative deviation)
    2. Compute S = std dev
    3. H = log(R/S) / log(window)

    Applied to |r_t| (absolute returns) as a proxy for the volatility process.
    Lower H → rougher process (anti-persistent).
    """
    n = len(returns)
    abs_ret = np.abs(returns)
    H = np.full(n, np.nan)

    for t in range(window, n):
        series = abs_ret[t - window:t]
        mean_s = np.mean(series)
        cumdev = np.cumsum(series - mean_s)
        R = np.max(cumdev) - np.min(cumdev)
        S = np.std(series, ddof=1)
        if S > 1e-12 and R > 0:
            RS = R / S
            H[t] = np.log(RS) / np.log(window)
        else:
            H[t] = 0.5  # neutral

    return H


def hurst_dfa(returns, window=63, scales=None):
    """
    Rolling Detrended Fluctuation Analysis (DFA) for Hurst exponent.

    Applied to |r_t| (absolute returns) as proxy for vol process.
    For each rolling window:
    1. Compute cumulative sum of (series - mean)
    2. For each scale s: divide into segments, detrend each, compute RMSE
    3. Regress log(F(s)) on log(s) → slope = H

    DFA is more robust than R/S for non-stationary series.
    """
    if scales is None:
        scales = [4, 8, 16, 32]

    n = len(returns)
    abs_ret = np.abs(returns)
    H = np.full(n, np.nan)

    for t in range(window, n):
        series = abs_ret[t - window:t]
        mean_s = np.mean(series)
        profile = np.cumsum(series - mean_s)

        log_s = []
        log_f = []
        for s in scales:
            if s > len(profile) // 2:
                continue
            n_segments = len(profile) // s
            if n_segments < 2:
                continue

            fluctuations = []
            for seg in range(n_segments):
                segment = profile[seg * s:(seg + 1) * s]
                # Linear detrend
                x_seg = np.arange(s)
                coeffs = np.polyfit(x_seg, segment, 1)
                trend = np.polyval(coeffs, x_seg)
                fluct = np.sqrt(np.mean((segment - trend) ** 2))
                fluctuations.append(fluct)

            if len(fluctuations) > 0:
                F_s = np.mean(fluctuations)
                if F_s > 0:
                    log_s.append(np.log(s))
                    log_f.append(np.log(F_s))

        if len(log_s) >= 2:
            slope, _, _, _, _ = stats.linregress(log_s, log_f)
            H[t] = slope
        else:
            H[t] = 0.5  # neutral

    return H


# ============================================================
# SECTION 2: DATA LOADING
# ============================================================
print("\n[2] Loading data...")
import yfinance as yf

# Download SPY
raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

# Combine
df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
df = df.dropna(subset=['log_ret'])
df = df.join(vix_data, how='left')
df['VIX'] = df['VIX'].ffill()
df = df.dropna()

print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# Diagnostics
ret_vals = df['log_ret'].values
desc = {
    'mean': float(np.mean(ret_vals)),
    'std': float(np.std(ret_vals)),
    'skewness': float(stats.skew(ret_vals)),
    'kurtosis': float(stats.kurtosis(ret_vals)),
    'n': int(len(ret_vals))
}
jb_stat, jb_p = stats.jarque_bera(ret_vals)
# ARCH LM test (10 lags)
ret2_lm = ret_vals ** 2
n_lm = len(ret2_lm) - 10
X_lm = np.column_stack([np.ones(n_lm)] + [ret2_lm[i:i + n_lm] for i in range(10)])
y_lm = ret2_lm[10:]
b_lm = np.linalg.lstsq(X_lm, y_lm, rcond=None)[0]
r2_lm_val = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
arch_lm = n_lm * r2_lm_val

print(f"  Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
      f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f} "
      f"JB={jb_stat:.0f}(p={jb_p:.1e}) ARCH_LM={arch_lm:.1f}")


# ============================================================
# SECTION 3: COMPUTE HURST TIME SERIES
# ============================================================
print("\n[3] Computing Hurst exponents...")

ret = df['log_ret'].values
t0 = time.time()
H_rs = hurst_rs(ret, window=HURST_WINDOW_RS)
t1 = time.time()
print(f"  R/S Hurst computed in {t1 - t0:.1f}s")

t0 = time.time()
H_dfa = hurst_dfa(ret, window=HURST_WINDOW_VAR, scales=DFA_SCALES)
t1 = time.time()
print(f"  DFA Hurst computed in {t1 - t0:.1f}s")

# Descriptive stats for Hurst series
valid_rs = H_rs[np.isfinite(H_rs)]
valid_dfa = H_dfa[np.isfinite(H_dfa)]

print(f"\n  R/S Hurst: mean={np.mean(valid_rs):.4f} std={np.std(valid_rs):.4f} "
      f"min={np.min(valid_rs):.4f} max={np.max(valid_rs):.4f}")
print(f"  DFA Hurst: mean={np.mean(valid_dfa):.4f} std={np.std(valid_dfa):.4f} "
      f"min={np.min(valid_dfa):.4f} max={np.max(valid_dfa):.4f}")

# Correlation between the two methods
both_valid = np.isfinite(H_rs) & np.isfinite(H_dfa)
if np.sum(both_valid) > 100:
    corr_methods, p_methods = stats.spearmanr(H_rs[both_valid], H_dfa[both_valid])
    print(f"  Correlation R/S vs DFA: rho={corr_methods:.4f} (p={p_methods:.2e})")

# Correlation with VIX
log_vix = np.log(df['VIX'].values)
h_vix_valid = np.isfinite(H_rs) & np.isfinite(log_vix)
if np.sum(h_vix_valid) > 100:
    corr_h_vix, p_h_vix = stats.spearmanr(H_rs[h_vix_valid], log_vix[h_vix_valid])
    print(f"  Correlation H_RS vs log(VIX): rho={corr_h_vix:.4f} (p={p_h_vix:.2e})")

# Choose primary Hurst method: use R/S (simpler, more established)
# Also test DFA as robustness check
H_primary = H_rs.copy()


# ============================================================
# SECTION 4: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[4] Model implementations...")


@njit(cache=True)
def garch_loglik(params, returns):
    """GARCH(1,1) log-likelihood. Returns negative LL for minimization."""
    omega, alpha, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0

    for t in range(1, n):
        h[t] = omega + alpha * returns[t - 1] ** 2 + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])

    return -ll


@njit(cache=True)
def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0

    for t in range(1, n):
        asym = gamma * returns[t - 1] ** 2 if returns[t - 1] < 0 else 0.0
        h[t] = omega + alpha * returns[t - 1] ** 2 + asym + beta * h[t - 1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t] ** 2 / h[t])

    return -ll


@njit(cache=True)
def garch_forecast_oos(params, r_prev, h_prev):
    """One-step GARCH forecast."""
    omega, alpha, beta = params
    h_next = omega + alpha * r_prev ** 2 + beta * h_prev
    return max(h_next, 1e-10)


@njit(cache=True)
def gjr_garch_forecast_oos(params, r_prev, h_prev):
    """One-step GJR-GARCH forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev ** 2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev ** 2 + asym + beta * h_prev
    return max(h_next, 1e-10)


def fit_garch(returns):
    """Fit GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-6, 0.05, 0.90],
        [1e-6, 0.08, 0.85],
        [1e-5, 0.03, 0.93],
        [5e-6, 0.06, 0.88],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: garch_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-6, 0.05, 0.05, 0.90],
        [1e-6, 0.08, 0.10, 0.85],
        [1e-5, 0.03, 0.03, 0.93],
        [5e-6, 0.06, 0.08, 0.88],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: gjr_garch_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def fit_mf_gjr(returns, log_vix, hurst=None, use_vix=True, use_hurst=False):
    """
    Fit MF-GJR with flexible long-run factor specification.

    Long-run: tau_t = exp(theta_0 + theta_1*log(VIX_{t-1}) + theta_2*H_{t-1})
    Short-run: g_t = GJR-GARCH(1,1) on u_t = r_t / sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t

    Args:
        returns: array of log returns
        log_vix: array of log(VIX)
        hurst: array of Hurst exponents (optional)
        use_vix: include VIX in tau specification
        use_hurst: include Hurst in tau specification
    """
    n = len(returns)

    # Lag the external factors
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    if hurst is not None:
        hurst_lag = np.roll(hurst, 1)
        hurst_lag[0] = hurst[0]
        # Replace NaN with mean for stability
        hurst_mean = np.nanmean(hurst)
        hurst_lag = np.where(np.isfinite(hurst_lag), hurst_lag, hurst_mean)
    else:
        hurst_lag = None

    # Determine param count based on specification
    # theta_0 always present
    # theta_1 if use_vix
    # theta_2 if use_hurst
    # Then: alpha, gamma, beta for GJR short-run
    n_theta = 1 + int(use_vix) + int(use_hurst)
    n_params = n_theta + 3  # + alpha, gamma, beta

    def neg_loglik(params):
        theta_idx = 0
        theta0 = params[theta_idx]
        theta_idx += 1

        # Build log_tau
        log_tau = np.full(n, theta0)

        if use_vix:
            theta1 = params[theta_idx]
            theta_idx += 1
            log_tau += theta1 * log_vix_lag
        if use_hurst:
            theta2 = params[theta_idx]
            theta_idx += 1
            log_tau += theta2 * hurst_lag

        alpha = params[theta_idx]
        gamma = params[theta_idx + 1]
        beta = params[theta_idx + 2]

        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        # Standardized returns
        u = returns / np.sqrt(tau)

        # Short-run GJR
        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0

        for t in range(1, n):
            asym = gamma * u[t - 1] ** 2 if u[t - 1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t - 1] ** 2 + asym + beta * g[t - 1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    # Initial values via OLS
    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)

    ols_vars = [np.ones(n)]
    if use_vix:
        ols_vars.append(log_vix_lag)
    if use_hurst:
        ols_vars.append(hurst_lag)
    X_ols = np.column_stack(ols_vars)
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    # Build starting points
    base_gjr = [0.05, 0.05, 0.90]

    starts = []
    for theta_scale in [1.0, 0.8, 1.2]:
        x0 = list(theta_init * theta_scale) + base_gjr
        starts.append(x0)
    # Additional starts with different GJR params
    starts.append(list(theta_init) + [0.08, 0.10, 0.85])
    starts.append(list(theta_init) + [0.03, 0.03, 0.93])

    # Bounds
    theta_bounds = [(-20, 0)]  # theta_0
    if use_vix:
        theta_bounds.append((-1, 3))  # theta_1
    if use_hurst:
        theta_bounds.append((-10, 10))  # theta_2 (wider range for Hurst)
    gjr_bounds = [(1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]
    bounds = theta_bounds + gjr_bounds

    best_ll = np.inf
    best_params = None

    for x0 in starts:
        try:
            res = optimize.minimize(
                neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None, None

    return best_params, -best_ll


def forecast_mf_gjr_insample(params, returns, log_vix, hurst=None,
                              use_vix=True, use_hurst=False):
    """Generate in-sample sigma^2 from MF-GJR. Returns sigma2, g, tau."""
    n = len(returns)

    theta_idx = 0
    theta0 = params[theta_idx]
    theta_idx += 1

    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    if hurst is not None:
        hurst_lag = np.roll(hurst, 1)
        hurst_lag[0] = hurst[0]
        hurst_mean = np.nanmean(hurst)
        hurst_lag = np.where(np.isfinite(hurst_lag), hurst_lag, hurst_mean)
    else:
        hurst_lag = None

    log_tau = np.full(n, theta0)
    if use_vix:
        theta1 = params[theta_idx]
        theta_idx += 1
        log_tau += theta1 * log_vix_lag
    if use_hurst:
        theta2 = params[theta_idx]
        theta_idx += 1
        log_tau += theta2 * hurst_lag

    alpha = params[theta_idx]
    gamma = params[theta_idx + 1]
    beta = params[theta_idx + 2]

    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)
    u = returns / np.sqrt(tau)

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t - 1] ** 2 if u[t - 1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t - 1] ** 2 + asym + beta * g[t - 1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 5: ROLLING OOS EVALUATION
# ============================================================
print("\n[5] Rolling OOS evaluation...")

ret = df['log_ret'].values
log_vix_raw = np.log(df['VIX'].values)
r2 = ret ** 2
dates = df.index

# Compute Hurst for full sample
H_rs_full = hurst_rs(ret, window=HURST_WINDOW_RS)
H_dfa_full = hurst_dfa(ret, window=HURST_WINDOW_VAR, scales=DFA_SCALES)

# Find OOS start index
oos_mask = dates >= OOS_START
oos_start_idx = np.argmax(oos_mask)
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
print(f"  OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

n_oos = len(ret) - oos_start_idx
print(f"  OOS days: {n_oos}")

# Model names and their specs
model_specs = {
    'GARCH': {'type': 'garch'},
    'GJR': {'type': 'gjr'},
    'MF-GJR(VIX)': {'type': 'mf', 'use_vix': True, 'use_hurst': False},
    'MF-GJR(H_RS)': {'type': 'mf', 'use_vix': False, 'use_hurst': True, 'hurst_method': 'rs'},
    'MF-GJR(H_DFA)': {'type': 'mf', 'use_vix': False, 'use_hurst': True, 'hurst_method': 'dfa'},
    'MF-GJR(VIX,H_RS)': {'type': 'mf', 'use_vix': True, 'use_hurst': True, 'hurst_method': 'rs'},
    'MF-GJR(VIX,H_DFA)': {'type': 'mf', 'use_vix': True, 'use_hurst': True, 'hurst_method': 'dfa'},
}

models = list(model_specs.keys())
forecasts = {m: np.full(n_oos, np.nan) for m in models}
oos_returns = ret[oos_start_idx:]
oos_r2 = r2[oos_start_idx:]
oos_dates = dates[oos_start_idx:]

# State tracking for recursive forecasting
state = {m: {} for m in models}

n_refits = 0
fit_times = {m: 0.0 for m in models}

for t in range(n_oos):
    idx = oos_start_idx + t
    need_refit = (t == 0) or (t % REFIT_EVERY == 0)

    # Training window
    train_start = max(0, idx - WINDOW)
    train_ret = ret[train_start:idx]
    train_vix = log_vix_raw[train_start:idx]
    train_H_rs = H_rs_full[train_start:idx]
    train_H_dfa = H_dfa_full[train_start:idx]

    if need_refit:
        n_refits += 1
        if t % (REFIT_EVERY * 5) == 0:
            elapsed = time.time() - START_TIME
            print(f"    t={t}/{n_oos} ({t / n_oos * 100:.0f}%) "
                  f"date={dates[idx]} elapsed={elapsed:.0f}s")

        # ---- Fit GARCH ----
        t0 = time.time()
        garch_params, _ = fit_garch(train_ret)
        fit_times['GARCH'] += time.time() - t0
        if garch_params is not None:
            state['GARCH']['params'] = garch_params
            h_arr = np.empty(len(train_ret))
            h_arr[0] = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                h_arr[tt] = garch_forecast_oos(garch_params, train_ret[tt - 1], h_arr[tt - 1])
            # Advance one step for OOS
            state['GARCH']['h'] = garch_forecast_oos(garch_params, train_ret[-1], h_arr[-1])

        # ---- Fit GJR ----
        t0 = time.time()
        gjr_params, _ = fit_gjr_garch(train_ret)
        fit_times['GJR'] += time.time() - t0
        if gjr_params is not None:
            state['GJR']['params'] = gjr_params
            h_arr = np.empty(len(train_ret))
            h_arr[0] = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                h_arr[tt] = gjr_garch_forecast_oos(gjr_params, train_ret[tt - 1], h_arr[tt - 1])
            state['GJR']['h'] = gjr_garch_forecast_oos(gjr_params, train_ret[-1], h_arr[-1])

        # ---- Fit MF-GJR variants ----
        for model_name in ['MF-GJR(VIX)', 'MF-GJR(H_RS)', 'MF-GJR(H_DFA)',
                           'MF-GJR(VIX,H_RS)', 'MF-GJR(VIX,H_DFA)']:
            spec = model_specs[model_name]
            use_vix = spec['use_vix']
            use_hurst = spec['use_hurst']
            hurst_method = spec.get('hurst_method', None)

            train_h = None
            if use_hurst:
                train_h = train_H_rs if hurst_method == 'rs' else train_H_dfa

            t0 = time.time()
            mf_params, mf_ll = fit_mf_gjr(
                train_ret, train_vix, hurst=train_h,
                use_vix=use_vix, use_hurst=use_hurst
            )
            fit_times[model_name] += time.time() - t0

            if mf_params is not None:
                state[model_name]['params'] = mf_params
                _, g_arr, tau_arr = forecast_mf_gjr_insample(
                    mf_params, train_ret, train_vix, hurst=train_h,
                    use_vix=use_vix, use_hurst=use_hurst
                )

                # Extract GJR params from mf_params
                n_theta = 1 + int(use_vix) + int(use_hurst)
                alpha_mf = mf_params[n_theta]
                gamma_mf = mf_params[n_theta + 1]
                beta_mf = mf_params[n_theta + 2]
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf

                # Advance g one step (bug fix #3 from K889v2)
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                asym = gamma_mf * u_last ** 2 if u_last < 0 else 0.0
                g_new = omega_g + alpha_mf * u_last ** 2 + asym + beta_mf * g_arr[-1]
                g_new = max(g_new, 1e-10)

                state[model_name]['g'] = g_new
                state[model_name]['tau_prev'] = tau_arr[-1]

    # === Generate one-step-ahead forecasts ===

    # GARCH
    if 'params' in state['GARCH']:
        if not need_refit and t > 0:
            state['GARCH']['h'] = garch_forecast_oos(
                state['GARCH']['params'], ret[idx - 1], state['GARCH']['h'])
        forecasts['GARCH'][t] = state['GARCH']['h']

    # GJR
    if 'params' in state['GJR']:
        if not need_refit and t > 0:
            state['GJR']['h'] = gjr_garch_forecast_oos(
                state['GJR']['params'], ret[idx - 1], state['GJR']['h'])
        forecasts['GJR'][t] = state['GJR']['h']

    # MF-GJR variants
    for model_name in ['MF-GJR(VIX)', 'MF-GJR(H_RS)', 'MF-GJR(H_DFA)',
                       'MF-GJR(VIX,H_RS)', 'MF-GJR(VIX,H_DFA)']:
        if 'params' not in state[model_name]:
            continue

        spec = model_specs[model_name]
        use_vix = spec['use_vix']
        use_hurst = spec['use_hurst']
        hurst_method = spec.get('hurst_method', None)
        params = state[model_name]['params']

        n_theta = 1 + int(use_vix) + int(use_hurst)
        theta0 = params[0]
        theta_idx = 1

        # Compute tau_t from yesterday's factors
        log_tau_t = theta0
        if use_vix:
            theta1 = params[theta_idx]
            theta_idx += 1
            log_tau_t += theta1 * log_vix_raw[idx - 1]
        if use_hurst:
            theta2 = params[theta_idx]
            theta_idx += 1
            h_val = H_rs_full[idx - 1] if hurst_method == 'rs' else H_dfa_full[idx - 1]
            if np.isfinite(h_val):
                log_tau_t += theta2 * h_val
            else:
                # Use training mean as fallback
                hurst_mean = np.nanmean(
                    H_rs_full[train_start:idx] if hurst_method == 'rs'
                    else H_dfa_full[train_start:idx]
                )
                log_tau_t += theta2 * hurst_mean

        tau_t = np.exp(log_tau_t)
        tau_t = max(tau_t, 1e-16)

        alpha_mf = params[n_theta]
        gamma_mf = params[n_theta + 1]
        beta_mf = params[n_theta + 2]
        omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf

        if need_refit:
            g_t = state[model_name]['g']
        else:
            # Update g using yesterday's standardized return
            tau_prev = state[model_name]['tau_prev']
            u_prev = ret[idx - 1] / np.sqrt(tau_prev)
            asym = gamma_mf * u_prev ** 2 if u_prev < 0 else 0.0
            g_t = omega_g + alpha_mf * u_prev ** 2 + asym + beta_mf * state[model_name]['g']
            g_t = max(g_t, 1e-10)

        state[model_name]['tau_prev'] = tau_t
        state[model_name]['g'] = g_t
        forecasts[model_name][t] = tau_t * g_t

print(f"\n  Refits: {n_refits}")
print(f"  Fit times: {json.dumps({k: f'{v:.1f}s' for k, v in fit_times.items()}, indent=2)}")


# ============================================================
# SECTION 6: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

# 6a: QLIKE on r^2
print("\n  === QLIKE on r^2 (Patton 2011) ===")
qlike_results = {}
for m in models:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        qlike_results[m] = qlike(oos_r2[valid], f[valid])
    else:
        qlike_results[m] = np.nan

gjr_qlike = qlike_results['GJR']
qlike_pct = {}
for m in models:
    if np.isfinite(qlike_results[m]) and np.isfinite(gjr_qlike) and gjr_qlike > 0:
        qlike_pct[m] = ((qlike_results[m] - gjr_qlike) / gjr_qlike) * 100
    else:
        qlike_pct[m] = np.nan

for m in models:
    pct = qlike_pct.get(m, np.nan)
    print(f"    {m:22s}: {qlike_results[m]:.6f} ({pct:+.3f}% vs GJR)")

# 6b: Spearman rank correlation
print("\n  === Spearman Rank Correlation ===")
spearman_results = {}
for m in models:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        rho, p = spearman_corr(oos_r2[valid], f[valid])
        spearman_results[m] = {'rho': float(rho), 'p': float(p)}
    else:
        spearman_results[m] = {'rho': np.nan, 'p': np.nan}

for m in models:
    r = spearman_results[m]
    print(f"    {m:22s}: rho={r['rho']:.4f} (p={r['p']:.2e})")

# 6c: DM tests (pairwise against GJR)
print("\n  === DM tests vs GJR (negative t = model is better) ===")
gjr_loss = qlike_pointwise(oos_r2, forecasts['GJR'])
dm_results = {}
for m in models:
    if m == 'GJR':
        dm_results[m] = {'t': 0.0, 'p': 1.0}
        continue
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0) & np.isfinite(gjr_loss)
    if valid.sum() > 100:
        m_loss = qlike_pointwise(oos_r2[valid], f[valid])
        t_stat, p_val = dm_test(m_loss, gjr_loss[valid])
        dm_results[m] = {'t': float(t_stat), 'p': float(p_val)}
    else:
        dm_results[m] = {'t': np.nan, 'p': np.nan}

for m in models:
    r = dm_results[m]
    sig = "*** HARVEY" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
    print(f"    {m:22s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

# 6d: DM tests - MF-GJR(VIX,H) vs MF-GJR(VIX) — the key test
print("\n  === KEY TEST: Does Hurst add to VIX? ===")
vix_loss = qlike_pointwise(oos_r2, forecasts['MF-GJR(VIX)'])

for hurst_model in ['MF-GJR(VIX,H_RS)', 'MF-GJR(VIX,H_DFA)']:
    f = forecasts[hurst_model]
    valid = np.isfinite(f) & (f > 0) & np.isfinite(vix_loss)
    if valid.sum() > 100:
        h_loss = qlike_pointwise(oos_r2[valid], f[valid])
        t_stat, p_val = dm_test(h_loss, vix_loss[valid])
        sig = "*** HARVEY" if abs(t_stat) > 3.0 else ("*" if abs(t_stat) > 1.96 else "NS")
        print(f"    {hurst_model} vs MF-GJR(VIX): t={t_stat:+.3f} (p={p_val:.4f}) {sig}")

        # Also compute QLIKE improvement
        q_vix = qlike(oos_r2[valid], forecasts['MF-GJR(VIX)'][valid])
        q_hurst = qlike(oos_r2[valid], f[valid])
        pct_imp = ((q_hurst - q_vix) / q_vix) * 100
        print(f"      QLIKE improvement over MF-GJR(VIX): {pct_imp:+.4f}%")

# 6e: DM tests - MF-GJR(H) vs GARCH — does Hurst alone help?
print("\n  === Does Hurst alone beat GARCH? ===")
garch_loss = qlike_pointwise(oos_r2, forecasts['GARCH'])

for hurst_model in ['MF-GJR(H_RS)', 'MF-GJR(H_DFA)']:
    f = forecasts[hurst_model]
    valid = np.isfinite(f) & (f > 0) & np.isfinite(garch_loss)
    if valid.sum() > 100:
        h_loss = qlike_pointwise(oos_r2[valid], f[valid])
        t_stat, p_val = dm_test(h_loss, garch_loss[valid])
        sig = "*** HARVEY" if abs(t_stat) > 3.0 else ("*" if abs(t_stat) > 1.96 else "NS")
        print(f"    {hurst_model} vs GARCH: t={t_stat:+.3f} (p={p_val:.4f}) {sig}")


# ============================================================
# SECTION 7: PARAMETER ANALYSIS
# ============================================================
print("\n[7] Parameter analysis...")

# Analyze final MF-GJR(VIX,H_RS) params
for model_name in ['MF-GJR(VIX)', 'MF-GJR(H_RS)', 'MF-GJR(VIX,H_RS)']:
    if 'params' in state[model_name]:
        params = state[model_name]['params']
        spec = model_specs[model_name]
        use_vix = spec['use_vix']
        use_hurst = spec['use_hurst']

        print(f"\n  {model_name} parameters:")
        idx = 0
        print(f"    theta_0 (intercept) = {params[idx]:.4f}")
        idx += 1
        if use_vix:
            print(f"    theta_1 (VIX)       = {params[idx]:.4f}")
            idx += 1
        if use_hurst:
            print(f"    theta_2 (Hurst)     = {params[idx]:.4f}")
            idx += 1
        print(f"    alpha (ARCH)        = {params[idx]:.4f}")
        print(f"    gamma (leverage)    = {params[idx + 1]:.4f}")
        print(f"    beta (GARCH)        = {params[idx + 2]:.4f}")
        pers = params[idx] + params[idx + 1] / 2.0 + params[idx + 2]
        print(f"    persistence         = {pers:.4f}")


# ============================================================
# SECTION 8: VISUALIZATION
# ============================================================
print("\n[8] Generating plots...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Plot 1: Hurst time series + VIX
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

# H(t) R/S
ax1 = axes[0]
valid_mask = np.isfinite(H_rs_full)
ax1.plot(dates[valid_mask], H_rs_full[valid_mask], color='blue', alpha=0.6, lw=0.8, label='H(t) R/S')
ax1.axhline(y=0.5, color='gray', ls='--', alpha=0.5, label='H=0.5 (random walk)')
ax1.axhline(y=np.nanmean(H_rs_full), color='red', ls='--', alpha=0.5,
            label=f'Mean={np.nanmean(H_rs_full):.3f}')
ax1.set_ylabel('Hurst (R/S)')
ax1.legend(loc='upper right', fontsize=8)
ax1.set_title('K936: Time-Varying Hurst Exponent (R/S) — SPY Absolute Returns')

# H(t) DFA
ax2 = axes[1]
valid_mask2 = np.isfinite(H_dfa_full)
ax2.plot(dates[valid_mask2], H_dfa_full[valid_mask2], color='green', alpha=0.6, lw=0.8, label='H(t) DFA')
ax2.axhline(y=0.5, color='gray', ls='--', alpha=0.5, label='H=0.5')
ax2.axhline(y=np.nanmean(H_dfa_full), color='red', ls='--', alpha=0.5,
            label=f'Mean={np.nanmean(H_dfa_full):.3f}')
ax2.set_ylabel('Hurst (DFA)')
ax2.legend(loc='upper right', fontsize=8)

# VIX
ax3 = axes[2]
ax3.plot(dates, df['VIX'].values, color='purple', alpha=0.6, lw=0.8, label='VIX')
ax3.set_ylabel('VIX')
ax3.legend(loc='upper right', fontsize=8)
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k936_hurst_timeseries.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k936_hurst_timeseries.png")

# Plot 2: Model comparison bar chart
fig, axes = plt.subplots(1, 3, figsize=(16, 5))

# QLIKE
ax = axes[0]
qlike_vals = [qlike_results[m] for m in models]
colors = ['gray', 'steelblue', 'darkblue', 'orange', 'darkorange', 'green', 'darkgreen']
bars = ax.bar(range(len(models)), qlike_vals, color=colors[:len(models)])
ax.set_xticks(range(len(models)))
ax.set_xticklabels([m.replace('MF-GJR', 'MF') for m in models], rotation=45, ha='right', fontsize=8)
ax.set_ylabel('QLIKE')
ax.set_title('QLIKE on r^2 (lower = better)')
# Highlight best
best_idx = np.nanargmin(qlike_vals)
bars[best_idx].set_edgecolor('red')
bars[best_idx].set_linewidth(2)

# Spearman
ax = axes[1]
spearman_vals = [spearman_results[m]['rho'] for m in models]
bars = ax.bar(range(len(models)), spearman_vals, color=colors[:len(models)])
ax.set_xticks(range(len(models)))
ax.set_xticklabels([m.replace('MF-GJR', 'MF') for m in models], rotation=45, ha='right', fontsize=8)
ax.set_ylabel('Spearman rho')
ax.set_title('Spearman Rank Correlation (higher = better)')
best_idx = np.nanargmax(spearman_vals)
bars[best_idx].set_edgecolor('red')
bars[best_idx].set_linewidth(2)

# DM t-stats vs GJR
ax = axes[2]
dm_vals = [dm_results[m]['t'] for m in models]
bar_colors = ['green' if v < -3.0 else ('lightgreen' if v < -1.96 else 'gray') for v in dm_vals]
ax.bar(range(len(models)), dm_vals, color=bar_colors)
ax.axhline(y=-3.0, color='red', ls='--', alpha=0.7, label='Harvey threshold')
ax.axhline(y=0, color='black', ls='-', alpha=0.3)
ax.set_xticks(range(len(models)))
ax.set_xticklabels([m.replace('MF-GJR', 'MF') for m in models], rotation=45, ha='right', fontsize=8)
ax.set_ylabel('DM t-stat')
ax.set_title('DM test vs GJR (negative = better)')
ax.legend(fontsize=8)

plt.suptitle(f'K936: Time-Varying Hurst Exponent — SPY OOS ({dates[oos_start_idx].strftime("%Y-%m-%d")} to {dates[-1].strftime("%Y-%m-%d")})',
             fontsize=11, y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k936_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k936_comparison.png")

# Plot 3: H(t) vs VIX scatter with lagged H
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

# Scatter: H_RS vs log(VIX)
ax = axes[0]
both_valid = np.isfinite(H_rs_full) & np.isfinite(log_vix_raw)
if np.sum(both_valid) > 100:
    ax.scatter(H_rs_full[both_valid], log_vix_raw[both_valid], alpha=0.1, s=3, color='blue')
    # Linear fit
    slope, intercept, r_value, _, _ = stats.linregress(H_rs_full[both_valid], log_vix_raw[both_valid])
    x_range = np.linspace(np.nanmin(H_rs_full[both_valid]), np.nanmax(H_rs_full[both_valid]), 100)
    ax.plot(x_range, slope * x_range + intercept, 'r-', lw=2,
            label=f'r={r_value:.3f}')
ax.set_xlabel('H(t) R/S')
ax.set_ylabel('log(VIX)')
ax.set_title('Hurst R/S vs log(VIX) — Concurrent')
ax.legend()

# Scatter: H_DFA vs log(VIX)
ax = axes[1]
both_valid2 = np.isfinite(H_dfa_full) & np.isfinite(log_vix_raw)
if np.sum(both_valid2) > 100:
    ax.scatter(H_dfa_full[both_valid2], log_vix_raw[both_valid2], alpha=0.1, s=3, color='green')
    slope, intercept, r_value, _, _ = stats.linregress(H_dfa_full[both_valid2], log_vix_raw[both_valid2])
    x_range = np.linspace(np.nanmin(H_dfa_full[both_valid2]), np.nanmax(H_dfa_full[both_valid2]), 100)
    ax.plot(x_range, slope * x_range + intercept, 'r-', lw=2,
            label=f'r={r_value:.3f}')
ax.set_xlabel('H(t) DFA')
ax.set_ylabel('log(VIX)')
ax.set_title('Hurst DFA vs log(VIX) — Concurrent')
ax.legend()

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k936_hurst_vix_scatter.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k936_hurst_vix_scatter.png")


# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
print("\n[9] Saving results...")

elapsed_total = time.time() - START_TIME

results = {
    "experiment_id": EXPERIMENT_ID,
    "title": "Time-Varying Hurst Exponent via Rolling Estimation",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "asset": "SPY",
    "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
    "oos_days": int(n_oos),
    "window": WINDOW,
    "refit_every": REFIT_EVERY,
    "hurst_window_rs": HURST_WINDOW_RS,
    "hurst_window_var": HURST_WINDOW_VAR,
    "n_refits": n_refits,
    "elapsed_seconds": round(elapsed_total, 1),
    "diagnostics": {
        "SPY": desc,
        "JB": {"stat": float(jb_stat), "p": float(jb_p)},
        "ARCH_LM": float(arch_lm),
    },
    "hurst_descriptive": {
        "RS": {
            "mean": float(np.nanmean(H_rs_full)),
            "std": float(np.nanstd(H_rs_full)),
            "min": float(np.nanmin(H_rs_full[np.isfinite(H_rs_full)])),
            "max": float(np.nanmax(H_rs_full[np.isfinite(H_rs_full)])),
        },
        "DFA": {
            "mean": float(np.nanmean(H_dfa_full)),
            "std": float(np.nanstd(H_dfa_full)),
            "min": float(np.nanmin(H_dfa_full[np.isfinite(H_dfa_full)])),
            "max": float(np.nanmax(H_dfa_full[np.isfinite(H_dfa_full)])),
        },
        "correlation_RS_DFA": float(corr_methods) if 'corr_methods' in dir() else None,
        "correlation_HRS_logVIX": float(corr_h_vix) if 'corr_h_vix' in dir() else None,
    },
    "qlike_results": {m: float(v) if np.isfinite(v) else None for m, v in qlike_results.items()},
    "qlike_pct_vs_gjr": {m: float(v) if np.isfinite(v) else None for m, v in qlike_pct.items()},
    "spearman_results": {m: {k: float(v) if np.isfinite(v) else None for k, v in r.items()}
                          for m, r in spearman_results.items()},
    "dm_vs_gjr": {m: {k: float(v) if np.isfinite(v) else None for k, v in r.items()}
                   for m, r in dm_results.items()},
    "parameters": {},
    "conclusions": {},
    "references": [
        "Gatheral, Jaisson & Rosenbaum (2018). Volatility is rough. QF 18(6):933-949.",
        "arXiv:2509.05820: EWMA-driven time-varying H in rBergomi",
        "Patton (2011). J Econometrics 160:246-256.",
        "Harvey et al. (2016). JBES 34:92-104.",
        "Engle, Ghysels & Sohn (2013). RES 95(3):776-797.",
    ]
}

# Parameters
for model_name in ['MF-GJR(VIX)', 'MF-GJR(H_RS)', 'MF-GJR(VIX,H_RS)']:
    if 'params' in state[model_name]:
        params = state[model_name]['params']
        spec = model_specs[model_name]
        param_dict = {}
        idx = 0
        param_dict['theta_0'] = float(params[idx])
        idx += 1
        if spec['use_vix']:
            param_dict['theta_1_VIX'] = float(params[idx])
            idx += 1
        if spec['use_hurst']:
            param_dict['theta_2_Hurst'] = float(params[idx])
            idx += 1
        param_dict['alpha'] = float(params[idx])
        param_dict['gamma'] = float(params[idx + 1])
        param_dict['beta'] = float(params[idx + 2])
        param_dict['persistence'] = float(params[idx] + params[idx + 1] / 2.0 + params[idx + 2])
        results['parameters'][model_name] = param_dict

# Conclusions
# Determine if Hurst adds incremental value
mfgjr_vix_qlike = qlike_results.get('MF-GJR(VIX)', np.nan)
mfgjr_vix_hrs_qlike = qlike_results.get('MF-GJR(VIX,H_RS)', np.nan)
mfgjr_hrs_qlike = qlike_results.get('MF-GJR(H_RS)', np.nan)
garch_qlike = qlike_results.get('GARCH', np.nan)

dm_vix_hrs = dm_results.get('MF-GJR(VIX,H_RS)', {})
dm_hrs = dm_results.get('MF-GJR(H_RS)', {})

conclusions = {
    "hurst_adds_to_vix": False,
    "hurst_alone_beats_garch": False,
    "hurst_alone_beats_gjr": False,
    "best_model": None,
    "interpretation": "",
}

# Check if MF-GJR(VIX,H) significantly beats MF-GJR(VIX)
vix_loss_full = qlike_pointwise(oos_r2, forecasts['MF-GJR(VIX)'])
for hm, label in [('MF-GJR(VIX,H_RS)', 'RS'), ('MF-GJR(VIX,H_DFA)', 'DFA')]:
    f = forecasts[hm]
    valid = np.isfinite(f) & (f > 0) & np.isfinite(vix_loss_full)
    if valid.sum() > 100:
        h_loss = qlike_pointwise(oos_r2[valid], f[valid])
        t_stat, p_val = dm_test(h_loss, vix_loss_full[valid])
        if t_stat < -3.0:
            conclusions['hurst_adds_to_vix'] = True
            conclusions[f'hurst_adds_to_vix_{label}'] = True
            conclusions[f'dm_vs_mfgjr_vix_{label}'] = {'t': float(t_stat), 'p': float(p_val)}
        else:
            conclusions[f'hurst_adds_to_vix_{label}'] = False
            conclusions[f'dm_vs_mfgjr_vix_{label}'] = {'t': float(t_stat), 'p': float(p_val)}

# Check if Hurst alone beats GARCH
for hm in ['MF-GJR(H_RS)', 'MF-GJR(H_DFA)']:
    dm_h = dm_results.get(hm, {})
    if dm_h.get('t', 0) < -3.0:
        conclusions['hurst_alone_beats_gjr'] = True

# Find best model
best_model = min(qlike_results, key=lambda m: qlike_results[m] if np.isfinite(qlike_results[m]) else np.inf)
conclusions['best_model'] = best_model

# Build interpretation
interp_parts = []
interp_parts.append(f"Best model by QLIKE: {best_model}")

if conclusions['hurst_adds_to_vix']:
    interp_parts.append("H(t) contains INCREMENTAL information beyond VIX (Harvey significant)")
else:
    interp_parts.append("H(t) does NOT add significant information beyond VIX")

if conclusions['hurst_alone_beats_gjr']:
    interp_parts.append("Hurst alone significantly beats GJR (standalone predictive power)")
else:
    interp_parts.append("Hurst alone does NOT significantly beat GJR")

# Check if Hurst info is subsumed by VIX
if not conclusions['hurst_adds_to_vix'] and conclusions['hurst_alone_beats_gjr']:
    interp_parts.append("CONCLUSION: Hurst has predictive power but is subsumed by VIX")
elif not conclusions['hurst_adds_to_vix'] and not conclusions['hurst_alone_beats_gjr']:
    interp_parts.append("CONCLUSION: Daily-frequency Hurst has no meaningful predictive power for volatility")
elif conclusions['hurst_adds_to_vix']:
    interp_parts.append("CONCLUSION: Hurst provides genuine incremental value beyond VIX")

conclusions['interpretation'] = "; ".join(interp_parts)
results['conclusions'] = conclusions

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {RESULTS_PATH}")


# ============================================================
# FINAL SUMMARY
# ============================================================
print("\n" + "=" * 70)
print(f"{EXPERIMENT_ID} SUMMARY")
print("=" * 70)
print(f"  Asset: SPY, OOS: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS days: {n_oos}, Refits: {n_refits}")
print(f"\n  Hurst descriptive (R/S): mean={np.nanmean(H_rs_full):.4f}, std={np.nanstd(H_rs_full):.4f}")
print(f"  Hurst descriptive (DFA): mean={np.nanmean(H_dfa_full):.4f}, std={np.nanstd(H_dfa_full):.4f}")
print(f"\n  Best model: {best_model}")
print(f"  Interpretation: {conclusions['interpretation']}")
print(f"\n  Total time: {elapsed_total:.0f}s")
print("=" * 70)
