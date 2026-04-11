"""
K1055: Conformal Prediction Intervals for A4f Volatility Forecasts
==================================================================

Compare conformal prediction intervals for A4f (multiplicative GARCH-X with VIX^2)
vs GJR-GARCH(1,1) on SPY daily returns.

Methods:
1. Split Conformal Prediction (Vovk et al. 2005, Lei et al. 2018)
2. Adaptive Conformal Inference (Gibbs & Candes 2021)

Evaluation:
- Empirical coverage at 90% and 95% nominal levels
- Average interval width (narrower = more precise at same coverage)
- Width ratio (A4f / GJR, <1 means A4f is more precise)
- Conditional coverage by VIX regime
- Winkler score (joint coverage + width loss)

References:
- Vovk, Gammerman, Shafer (2005). Algorithmic Learning in a Random World
- Lei et al. (2018). Distribution-Free Predictive Inference
- Gibbs & Candes (2021). Adaptive Conformal Inference Under Distribution Shift
- Barber et al. (2023). Conformal prediction beyond exchangeability

Data source: yfinance (SPY + ^VIX), 2005-2026
Target: r^2 (squared daily return) as proxy for sigma^2

Random seed: 42
"""

import numpy as np
import pandas as pd
import json
import time
import os
import warnings
from scipy.optimize import minimize
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
START_TIME = time.time()

# ============================================================
# Configuration
# ============================================================
WINDOW = 2000          # Training window for GARCH estimation
REFIT_EVERY = 63       # Refit every quarter (~63 trading days)
OOS_START = '2019-01-02'
CALIB_WINDOW = 252     # Rolling calibration window for conformal scores
ALPHA_LEVELS = [0.10, 0.05]  # For 90% and 95% coverage
ACI_GAMMA = 0.01       # Learning rate for Adaptive Conformal Inference

# ============================================================
# Data Download
# ============================================================
print("=" * 60)
print("K1055: Conformal Prediction Intervals for A4f vs GJR")
print("=" * 60)

import yfinance as yf

spy = yf.download('SPY', start='2004-01-01', end='2026-04-11', progress=False)
vix_data = yf.download('^VIX', start='2004-01-01', end='2026-04-11', progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix_data.columns, pd.MultiIndex):
    vix_data.columns = vix_data.columns.get_level_values(0)

spy_close = spy['Close'].dropna()
vix_close = vix_data['Close'].dropna()

# Align dates
common_dates = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common_dates]
vix_close = vix_close.loc[common_dates]

# Returns
ret = np.log(spy_close / spy_close.shift(1)).dropna()
vix_aligned = vix_close.reindex(ret.index).ffill()

# Ensure no NaN
mask = ~(ret.isna() | vix_aligned.isna())
ret = ret[mask]
vix_aligned = vix_aligned[mask]

dates = ret.index
ret_vals = ret.values.astype(float)
vix_vals = vix_aligned.values.astype(float)
log_vix_vals = np.log(np.maximum(vix_vals, 1.0))
r2_vals = ret_vals ** 2  # Target: squared returns

n_total = len(ret_vals)
print(f"Data: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}, N={n_total}")

# Descriptive statistics
print(f"\nDescriptive Statistics (daily returns):")
print(f"  Mean:    {np.mean(ret_vals)*252:.4f} (annualized)")
print(f"  Std:     {np.std(ret_vals)*np.sqrt(252):.4f} (annualized)")
print(f"  Skew:    {pd.Series(ret_vals).skew():.4f}")
print(f"  Kurt:    {pd.Series(ret_vals).kurtosis():.4f}")
print(f"  VIX range: {np.min(vix_vals):.1f} - {np.max(vix_vals):.1f}")


# ============================================================
# Model Implementations
# ============================================================

def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) by MLE."""
    n = len(returns)
    var0 = np.var(returns)

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        h = np.empty(n)
        h[0] = var0
        for t in range(1, n):
            asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
            h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
            if h[t] < 1e-12:
                h[t] = 1e-12

        ll = 0.0
        for t in range(n):
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
        return -ll

    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-10, 1e-3), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    for s in starts:
        try:
            res = minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except:
            pass
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-12)


def compute_tau_a4f(theta0, theta1, vix_lag_sq):
    """Compute tau for A4f: tau = theta0 + theta1 * VIX_lag^2."""
    return max(theta0 + theta1 * vix_lag_sq, 1e-16)


def fit_a4f(returns, vix_vals_train):
    """
    Fit A4f: multiplicative GJR-GARCH-X with VIX^2 tau function.
    sigma^2_t = tau_t * g_t
    tau_t = theta0 + theta1 * VIX_{t-1}^2
    g_t = omega + alpha * u_{t-1}^2 + gamma * u_{t-1}^2 * I(u<0) + beta * g_{t-1}
    u_t = r_t / sqrt(tau_t)
    free_omega version (6 parameters)
    """
    n = len(returns)

    # Lagged VIX^2 (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals_train[0]
    vix_lag[1:] = vix_vals_train[:-1]
    vix_lag_sq = vix_lag ** 2

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag_sq) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if alpha + gamma_p / 2.0 + beta >= 0.999:
            return 1e10

        # tau
        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)

        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t-1])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

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
            res = minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except:
            pass

    return best_params


# ============================================================
# OOS Forecasting (rolling)
# ============================================================
oos_start_idx = np.searchsorted(dates, pd.Timestamp(OOS_START))
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
n_oos = n_total - oos_start_idx

print(f"\nOOS period: {dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
print(f"OOS days: {n_oos}")
print(f"Refit every {REFIT_EVERY} days")

# Storage for forecasts
gjr_forecasts = np.full(n_oos, np.nan)
a4f_forecasts = np.full(n_oos, np.nan)
oos_dates = dates[oos_start_idx:]
oos_r2 = r2_vals[oos_start_idx:]

# States
gjr_params = None
gjr_h = None
a4f_params = None
a4f_g = None
a4f_tau_prev = None

refit_count = 0
print("\nStarting OOS forecasting...")

for t_idx in range(n_oos):
    abs_idx = oos_start_idx + t_idx

    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret_vals[train_start:abs_idx]
        train_vix = vix_vals[train_start:abs_idx]

        # Fit GJR
        gjr_params_new = fit_gjr(train_ret)
        if gjr_params_new is not None:
            gjr_params = gjr_params_new
            # Initialize h from training data
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h

        # Fit A4f
        a4f_params_new = fit_a4f(train_ret, train_vix)
        if a4f_params_new is not None:
            a4f_params = a4f_params_new
            theta0, theta1 = a4f_params[0], a4f_params[1]
            omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]

            # Initialize g from training
            n_train = len(train_ret)
            vix_lag_tr = np.empty(n_train)
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            vix_lag_sq_tr = vix_lag_tr ** 2

            persist = alpha_p + gamma_p / 2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, n_train):
                tau_i = max(theta0 + theta1 * vix_lag_sq_tr[i], 1e-16)
                u_prev = train_ret[i-1] / np.sqrt(max(theta0 + theta1 * vix_lag_sq_tr[i-1], 1e-16))
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)

            a4f_g = g
            # tau for the last training day
            a4f_tau_prev = max(theta0 + theta1 * vix_lag_sq_tr[-1], 1e-16)

    # Generate forecasts for day abs_idx

    # GJR forecast
    if gjr_params is not None and gjr_h is not None:
        r_prev = ret_vals[abs_idx - 1]
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_h = h_new

    # A4f forecast
    if a4f_params is not None and a4f_g is not None:
        theta0, theta1 = a4f_params[0], a4f_params[1]
        omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]

        # tau_t uses VIX_{t-1} (predetermined, no lookahead)
        vix_lag_sq_t = vix_vals[abs_idx - 1] ** 2
        tau_t = max(theta0 + theta1 * vix_lag_sq_t, 1e-16)

        # Update g using r_{t-1} and tau_{t-1}
        r_prev = ret_vals[abs_idx - 1]
        u_prev = r_prev / np.sqrt(max(a4f_tau_prev, 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)

        a4f_forecasts[t_idx] = tau_t * g_new
        a4f_g = g_new
        a4f_tau_prev = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# Validate forecasts
gjr_valid = ~np.isnan(gjr_forecasts)
a4f_valid = ~np.isnan(a4f_forecasts)
both_valid = gjr_valid & a4f_valid
print(f"  GJR valid: {np.sum(gjr_valid)}, A4f valid: {np.sum(a4f_valid)}, both: {np.sum(both_valid)}")


# ============================================================
# QLIKE evaluation (sanity check)
# ============================================================
def qlike(target, forecast):
    """QLIKE loss: mean(target/forecast + log(forecast))"""
    valid = (forecast > 0) & (target >= 0) & np.isfinite(target) & np.isfinite(forecast)
    t = target[valid]
    f = forecast[valid]
    return np.mean(t / f + np.log(f))

qlike_gjr = qlike(oos_r2[both_valid], gjr_forecasts[both_valid])
qlike_a4f = qlike(oos_r2[both_valid], a4f_forecasts[both_valid])
print(f"\nQLIKE sanity check:")
print(f"  GJR: {qlike_gjr:.6f}")
print(f"  A4f: {qlike_a4f:.6f}")
print(f"  A4f improvement: {(qlike_gjr - qlike_a4f) / qlike_gjr * 100:.2f}%")


# ============================================================
# Conformal Prediction
# ============================================================
print("\n" + "=" * 60)
print("CONFORMAL PREDICTION ANALYSIS")
print("=" * 60)

def compute_nonconformity_scores(target, forecast):
    """
    Relative nonconformity scores: |target - forecast| / forecast
    Using relative scores so intervals scale with forecast magnitude.
    """
    valid = (forecast > 0) & np.isfinite(target) & np.isfinite(forecast)
    scores = np.full(len(target), np.nan)
    scores[valid] = np.abs(target[valid] - forecast[valid]) / forecast[valid]
    return scores


def split_conformal_intervals(target, forecast, calib_window, alpha):
    """
    Rolling split conformal prediction intervals.
    Uses past calib_window days as calibration set.
    Returns lower, upper bounds and coverage indicators.
    """
    n = len(target)
    scores = compute_nonconformity_scores(target, forecast)

    lower = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    covered = np.full(n, np.nan)
    widths = np.full(n, np.nan)
    q_vals = np.full(n, np.nan)

    for t in range(calib_window, n):
        # Calibration scores from past window
        calib_scores = scores[t - calib_window:t]
        valid_scores = calib_scores[~np.isnan(calib_scores)]

        if len(valid_scores) < 50:
            continue

        # Conformal quantile: (1-alpha)(1 + 1/n_calib) quantile
        # Finite-sample correction per Vovk et al. (2005)
        q_level = min((1 - alpha) * (1 + 1 / len(valid_scores)), 1.0)
        q = np.quantile(valid_scores, q_level)
        q_vals[t] = q

        # Prediction interval
        f_t = forecast[t]
        if f_t > 0 and np.isfinite(f_t):
            lower[t] = f_t * max(1 - q, 0)  # Lower bound (non-negative)
            upper[t] = f_t * (1 + q)
            widths[t] = upper[t] - lower[t]

            # Check coverage
            if np.isfinite(target[t]):
                covered[t] = 1.0 if (lower[t] <= target[t] <= upper[t]) else 0.0

    return lower, upper, covered, widths, q_vals


def adaptive_conformal_intervals(target, forecast, calib_window, alpha, gamma_aci=0.01):
    """
    Adaptive Conformal Inference (Gibbs & Candes 2021).
    Dynamically adjusts alpha_t based on recent coverage.
    alpha_{t+1} = alpha_t + gamma * (alpha - err_t)
    """
    n = len(target)
    scores = compute_nonconformity_scores(target, forecast)

    lower = np.full(n, np.nan)
    upper = np.full(n, np.nan)
    covered = np.full(n, np.nan)
    widths = np.full(n, np.nan)
    alpha_t_vals = np.full(n, np.nan)

    alpha_t = alpha  # Initial alpha

    for t in range(calib_window, n):
        alpha_t_vals[t] = alpha_t

        # Calibration scores from past window
        calib_scores = scores[t - calib_window:t]
        valid_scores = calib_scores[~np.isnan(calib_scores)]

        if len(valid_scores) < 50:
            continue

        # Use adaptive alpha_t for quantile
        alpha_clamped = max(min(alpha_t, 0.5), 0.001)  # Clamp to reasonable range
        q_level = min((1 - alpha_clamped) * (1 + 1 / len(valid_scores)), 1.0)
        q = np.quantile(valid_scores, q_level)

        f_t = forecast[t]
        if f_t > 0 and np.isfinite(f_t):
            lower[t] = f_t * max(1 - q, 0)
            upper[t] = f_t * (1 + q)
            widths[t] = upper[t] - lower[t]

            if np.isfinite(target[t]):
                err_t = 1.0 if not (lower[t] <= target[t] <= upper[t]) else 0.0
                covered[t] = 1.0 - err_t

                # Update alpha_t: Gibbs & Candes (2021) update rule
                alpha_t = alpha_t + gamma_aci * (alpha - err_t)
                # err_t=1 (miss): alpha_t decreases -> wider interval
                # err_t=0 (hit): alpha_t increases -> narrower interval

    return lower, upper, covered, widths, alpha_t_vals


def winkler_score(target, lower, upper, alpha):
    """
    Winkler (1972) interval score.
    Penalizes both width and non-coverage.
    Lower is better.
    """
    valid = np.isfinite(target) & np.isfinite(lower) & np.isfinite(upper)
    scores = []
    for i in range(len(target)):
        if not valid[i]:
            continue
        w = upper[i] - lower[i]
        if target[i] < lower[i]:
            scores.append(w + (2 / alpha) * (lower[i] - target[i]))
        elif target[i] > upper[i]:
            scores.append(w + (2 / alpha) * (target[i] - upper[i]))
        else:
            scores.append(w)
    return np.mean(scores) if scores else np.nan


# ============================================================
# Run Conformal Analysis
# ============================================================

# Use only days where both models have valid forecasts
mask = both_valid
target = oos_r2.copy()

results = {}

for alpha in ALPHA_LEVELS:
    nominal_cov = 1 - alpha
    print(f"\n--- Nominal Coverage: {nominal_cov*100:.0f}% (alpha={alpha}) ---")

    for model_name, forecasts in [('GJR', gjr_forecasts), ('A4f', a4f_forecasts)]:
        print(f"\n  Model: {model_name}")

        # Split Conformal
        sc_lower, sc_upper, sc_covered, sc_widths, sc_q = \
            split_conformal_intervals(target, forecasts, CALIB_WINDOW, alpha)

        # Adaptive Conformal
        ac_lower, ac_upper, ac_covered, ac_widths, ac_alpha_t = \
            adaptive_conformal_intervals(target, forecasts, CALIB_WINDOW, alpha, ACI_GAMMA)

        # Compute metrics (only where valid)
        sc_valid = ~np.isnan(sc_covered)
        ac_valid = ~np.isnan(ac_covered)

        sc_coverage = np.nanmean(sc_covered[sc_valid]) if np.any(sc_valid) else np.nan
        ac_coverage = np.nanmean(ac_covered[ac_valid]) if np.any(ac_valid) else np.nan

        sc_avg_width = np.nanmean(sc_widths[sc_valid]) if np.any(sc_valid) else np.nan
        ac_avg_width = np.nanmean(ac_widths[ac_valid]) if np.any(ac_valid) else np.nan

        sc_median_width = np.nanmedian(sc_widths[sc_valid]) if np.any(sc_valid) else np.nan
        ac_median_width = np.nanmedian(ac_widths[ac_valid]) if np.any(ac_valid) else np.nan

        sc_winkler = winkler_score(target, sc_lower, sc_upper, alpha)
        ac_winkler = winkler_score(target, ac_lower, ac_upper, alpha)

        print(f"    Split Conformal:")
        print(f"      Coverage: {sc_coverage:.4f} (nominal: {nominal_cov:.2f})")
        print(f"      Avg width: {sc_avg_width:.6f}")
        print(f"      Median width: {sc_median_width:.6f}")
        print(f"      Winkler: {sc_winkler:.6f}")
        print(f"      N valid: {np.sum(sc_valid)}")

        print(f"    Adaptive Conformal:")
        print(f"      Coverage: {ac_coverage:.4f} (nominal: {nominal_cov:.2f})")
        print(f"      Avg width: {ac_avg_width:.6f}")
        print(f"      Median width: {ac_median_width:.6f}")
        print(f"      Winkler: {ac_winkler:.6f}")
        print(f"      N valid: {np.sum(ac_valid)}")

        key = f"{model_name}_{nominal_cov*100:.0f}"
        results[key] = {
            'model': model_name,
            'nominal_coverage': nominal_cov,
            'split_conformal': {
                'coverage': float(sc_coverage),
                'avg_width': float(sc_avg_width),
                'median_width': float(sc_median_width),
                'winkler_score': float(sc_winkler),
                'n_valid': int(np.sum(sc_valid)),
            },
            'adaptive_conformal': {
                'coverage': float(ac_coverage),
                'avg_width': float(ac_avg_width),
                'median_width': float(ac_median_width),
                'winkler_score': float(ac_winkler),
                'n_valid': int(np.sum(ac_valid)),
            },
            # Store arrays for plotting
            '_sc_lower': sc_lower,
            '_sc_upper': sc_upper,
            '_sc_covered': sc_covered,
            '_sc_widths': sc_widths,
            '_ac_lower': ac_lower,
            '_ac_upper': ac_upper,
            '_ac_covered': ac_covered,
            '_ac_widths': ac_widths,
            '_ac_alpha_t': ac_alpha_t,
        }


# ============================================================
# Width Ratio Comparison (A4f vs GJR)
# ============================================================
print("\n" + "=" * 60)
print("WIDTH RATIO COMPARISON (A4f / GJR)")
print("=" * 60)

width_ratios = {}
for alpha in ALPHA_LEVELS:
    nominal_cov = 1 - alpha
    key_gjr = f"GJR_{nominal_cov*100:.0f}"
    key_a4f = f"A4f_{nominal_cov*100:.0f}"

    for method in ['split_conformal', 'adaptive_conformal']:
        gjr_w = results[key_gjr][method]['avg_width']
        a4f_w = results[key_a4f][method]['avg_width']
        ratio = a4f_w / gjr_w if gjr_w > 0 else np.nan

        gjr_wink = results[key_gjr][method]['winkler_score']
        a4f_wink = results[key_a4f][method]['winkler_score']
        wink_ratio = a4f_wink / gjr_wink if gjr_wink > 0 else np.nan

        label = f"{nominal_cov*100:.0f}%_{method}"
        width_ratios[label] = {
            'width_ratio': float(ratio),
            'winkler_ratio': float(wink_ratio),
            'a4f_coverage': results[key_a4f][method]['coverage'],
            'gjr_coverage': results[key_gjr][method]['coverage'],
        }

        print(f"\n  {nominal_cov*100:.0f}% {method}:")
        print(f"    Width ratio (A4f/GJR): {ratio:.4f} {'<-- A4f narrower' if ratio < 1 else '<-- GJR narrower'}")
        print(f"    Winkler ratio (A4f/GJR): {wink_ratio:.4f} {'<-- A4f better' if wink_ratio < 1 else '<-- GJR better'}")
        print(f"    A4f coverage: {results[key_a4f][method]['coverage']:.4f}")
        print(f"    GJR coverage: {results[key_gjr][method]['coverage']:.4f}")


# ============================================================
# Conditional Coverage by VIX Regime
# ============================================================
print("\n" + "=" * 60)
print("CONDITIONAL COVERAGE BY VIX REGIME")
print("=" * 60)

oos_vix = vix_vals[oos_start_idx:]
vix_regimes = {
    'Low (VIX<15)': oos_vix < 15,
    'Medium (15-25)': (oos_vix >= 15) & (oos_vix < 25),
    'High (25-35)': (oos_vix >= 25) & (oos_vix < 35),
    'Crisis (VIX>=35)': oos_vix >= 35,
}

regime_results = {}
alpha_test = 0.10  # Use 90% for regime analysis
nominal_cov = 0.90

for regime_name, regime_mask in vix_regimes.items():
    n_regime = np.sum(regime_mask)
    if n_regime < 20:
        print(f"\n  {regime_name}: N={n_regime} (too few)")
        continue

    print(f"\n  {regime_name}: N={n_regime}")

    regime_data = {}
    for model_name in ['GJR', 'A4f']:
        key = f"{model_name}_{nominal_cov*100:.0f}"
        sc_covered = results[key]['_sc_covered']
        sc_widths = results[key]['_sc_widths']
        ac_covered = results[key]['_ac_covered']
        ac_widths = results[key]['_ac_widths']

        # Filter to regime
        regime_sc_cov = sc_covered[regime_mask]
        regime_sc_w = sc_widths[regime_mask]
        regime_ac_cov = ac_covered[regime_mask]
        regime_ac_w = ac_widths[regime_mask]

        sc_cov_val = np.nanmean(regime_sc_cov) if np.any(~np.isnan(regime_sc_cov)) else np.nan
        sc_w_val = np.nanmean(regime_sc_w) if np.any(~np.isnan(regime_sc_w)) else np.nan
        ac_cov_val = np.nanmean(regime_ac_cov) if np.any(~np.isnan(regime_ac_cov)) else np.nan
        ac_w_val = np.nanmean(regime_ac_w) if np.any(~np.isnan(regime_ac_w)) else np.nan

        print(f"    {model_name} Split: cov={sc_cov_val:.4f}, width={sc_w_val:.6f}")
        print(f"    {model_name} ACI:   cov={ac_cov_val:.4f}, width={ac_w_val:.6f}")

        regime_data[model_name] = {
            'split_coverage': float(sc_cov_val) if np.isfinite(sc_cov_val) else None,
            'split_avg_width': float(sc_w_val) if np.isfinite(sc_w_val) else None,
            'aci_coverage': float(ac_cov_val) if np.isfinite(ac_cov_val) else None,
            'aci_avg_width': float(ac_w_val) if np.isfinite(ac_w_val) else None,
            'n_days': int(np.sum(~np.isnan(regime_sc_cov))),
        }

    regime_results[regime_name] = regime_data


# ============================================================
# Rolling Coverage Rate (for time-series plot)
# ============================================================
print("\n" + "=" * 60)
print("ROLLING COVERAGE ANALYSIS")
print("=" * 60)

ROLLING_WINDOW = 126  # ~6 months

rolling_coverage = {}
for model_name in ['GJR', 'A4f']:
    key = f"{model_name}_90"
    sc_covered = results[key]['_sc_covered']
    ac_covered = results[key]['_ac_covered']

    rc_sc = pd.Series(sc_covered).rolling(ROLLING_WINDOW, min_periods=60).mean()
    rc_ac = pd.Series(ac_covered).rolling(ROLLING_WINDOW, min_periods=60).mean()

    rolling_coverage[f"{model_name}_sc"] = rc_sc.values
    rolling_coverage[f"{model_name}_ac"] = rc_ac.values

    valid_rc_sc = rc_sc.dropna()
    valid_rc_ac = rc_ac.dropna()

    print(f"\n  {model_name} rolling coverage (126-day):")
    print(f"    Split: min={valid_rc_sc.min():.4f}, max={valid_rc_sc.max():.4f}, std={valid_rc_sc.std():.4f}")
    print(f"    ACI:   min={valid_rc_ac.min():.4f}, max={valid_rc_ac.max():.4f}, std={valid_rc_ac.std():.4f}")


# ============================================================
# Model Failure Detection
# ============================================================
print("\n" + "=" * 60)
print("MODEL FAILURE DETECTION (Interval Width Spikes)")
print("=" * 60)

failure_analysis = {}
for model_name in ['GJR', 'A4f']:
    key = f"{model_name}_90"
    sc_widths = results[key]['_sc_widths']

    valid_w = sc_widths[~np.isnan(sc_widths)]
    if len(valid_w) == 0:
        continue

    median_w = np.median(valid_w)
    mad_w = np.median(np.abs(valid_w - median_w))

    # Flag days where width > median + 3*MAD
    threshold = median_w + 3 * mad_w
    spike_mask = sc_widths > threshold
    n_spikes = np.sum(spike_mask & ~np.isnan(sc_widths))

    # Check if spikes correlate with high VIX
    spike_vix = oos_vix[spike_mask & ~np.isnan(sc_widths)] if np.any(spike_mask & ~np.isnan(sc_widths)) else np.array([])

    print(f"\n  {model_name}:")
    print(f"    Median width: {median_w:.6f}")
    print(f"    MAD: {mad_w:.6f}")
    print(f"    Spike threshold: {threshold:.6f}")
    print(f"    N spikes: {n_spikes}")
    if len(spike_vix) > 0:
        print(f"    Mean VIX at spikes: {np.mean(spike_vix):.1f}")
        print(f"    Normal VIX mean: {np.mean(oos_vix):.1f}")

    failure_analysis[model_name] = {
        'median_width': float(median_w),
        'mad': float(mad_w),
        'spike_threshold': float(threshold),
        'n_spikes': int(n_spikes),
        'mean_vix_at_spikes': float(np.mean(spike_vix)) if len(spike_vix) > 0 else None,
        'mean_vix_overall': float(np.mean(oos_vix)),
    }


# ============================================================
# Bootstrap test: is A4f width significantly narrower?
# ============================================================
print("\n" + "=" * 60)
print("BOOTSTRAP TEST: Width Difference Significance")
print("=" * 60)

for alpha in ALPHA_LEVELS:
    nominal_cov = 1 - alpha
    key_gjr = f"GJR_{nominal_cov*100:.0f}"
    key_a4f = f"A4f_{nominal_cov*100:.0f}"

    # Get paired widths for split conformal
    gjr_w = results[key_gjr]['_sc_widths']
    a4f_w = results[key_a4f]['_sc_widths']

    both_valid_w = ~np.isnan(gjr_w) & ~np.isnan(a4f_w)
    gjr_w_valid = gjr_w[both_valid_w]
    a4f_w_valid = a4f_w[both_valid_w]

    if len(gjr_w_valid) < 100:
        print(f"\n  {nominal_cov*100:.0f}%: Not enough paired observations")
        continue

    diff = gjr_w_valid - a4f_w_valid  # Positive = A4f narrower
    observed_diff = np.mean(diff)

    # Bootstrap
    n_boot = 10000
    rng = np.random.default_rng(42)
    boot_diffs = np.empty(n_boot)
    n_pairs = len(diff)
    for b in range(n_boot):
        idx = rng.integers(0, n_pairs, n_pairs)
        boot_diffs[b] = np.mean(diff[idx])

    ci_low = np.percentile(boot_diffs, 2.5)
    ci_high = np.percentile(boot_diffs, 97.5)
    se = np.std(boot_diffs)
    t_stat = observed_diff / se if se > 0 else 0

    print(f"\n  {nominal_cov*100:.0f}% Split Conformal:")
    print(f"    Mean width diff (GJR - A4f): {observed_diff:.6f}")
    print(f"    Bootstrap SE: {se:.6f}")
    print(f"    t-stat: {t_stat:.3f}")
    print(f"    95% CI: [{ci_low:.6f}, {ci_high:.6f}]")
    print(f"    Significant (>0 = A4f narrower): {'YES' if ci_low > 0 else 'NO'}")

    # Also bootstrap Winkler score difference
    gjr_wink_scores = []
    a4f_wink_scores = []
    for i in range(len(gjr_w_valid)):
        idx_orig = np.where(both_valid_w)[0][i]
        t_val = target[idx_orig]
        # GJR
        g_l = results[key_gjr]['_sc_lower'][idx_orig]
        g_u = results[key_gjr]['_sc_upper'][idx_orig]
        # A4f
        a_l = results[key_a4f]['_sc_lower'][idx_orig]
        a_u = results[key_a4f]['_sc_upper'][idx_orig]

        if not (np.isfinite(t_val) and np.isfinite(g_l) and np.isfinite(a_l)):
            continue

        w_g = g_u - g_l
        w_a = a_u - a_l

        # Winkler scores
        if t_val < g_l:
            ws_g = w_g + (2/alpha) * (g_l - t_val)
        elif t_val > g_u:
            ws_g = w_g + (2/alpha) * (t_val - g_u)
        else:
            ws_g = w_g

        if t_val < a_l:
            ws_a = w_a + (2/alpha) * (a_l - t_val)
        elif t_val > a_u:
            ws_a = w_a + (2/alpha) * (t_val - a_u)
        else:
            ws_a = w_a

        gjr_wink_scores.append(ws_g)
        a4f_wink_scores.append(ws_a)

    gjr_wink_arr = np.array(gjr_wink_scores)
    a4f_wink_arr = np.array(a4f_wink_scores)
    wink_diff = gjr_wink_arr - a4f_wink_arr  # Positive = A4f better
    obs_wink_diff = np.mean(wink_diff)

    boot_wink_diffs = np.empty(n_boot)
    n_w = len(wink_diff)
    for b in range(n_boot):
        idx = rng.integers(0, n_w, n_w)
        boot_wink_diffs[b] = np.mean(wink_diff[idx])

    wink_ci_low = np.percentile(boot_wink_diffs, 2.5)
    wink_ci_high = np.percentile(boot_wink_diffs, 97.5)
    wink_se = np.std(boot_wink_diffs)
    wink_t = obs_wink_diff / wink_se if wink_se > 0 else 0

    print(f"    Winkler diff (GJR - A4f): {obs_wink_diff:.6f}")
    print(f"    Bootstrap SE: {wink_se:.6f}")
    print(f"    t-stat: {wink_t:.3f}")
    print(f"    95% CI: [{wink_ci_low:.6f}, {wink_ci_high:.6f}]")
    print(f"    Significant (>0 = A4f better): {'YES' if wink_ci_low > 0 else 'NO'}")

    width_ratios[f"{nominal_cov*100:.0f}%_bootstrap"] = {
        'width_diff_mean': float(observed_diff),
        'width_diff_se': float(se),
        'width_diff_t': float(t_stat),
        'width_diff_ci': [float(ci_low), float(ci_high)],
        'width_diff_significant': bool(ci_low > 0),
        'winkler_diff_mean': float(obs_wink_diff),
        'winkler_diff_se': float(wink_se),
        'winkler_diff_t': float(wink_t),
        'winkler_diff_ci': [float(wink_ci_low), float(wink_ci_high)],
        'winkler_diff_significant': bool(wink_ci_low > 0),
    }


# ============================================================
# Plotting
# ============================================================
print("\n" + "=" * 60)
print("GENERATING PLOTS")
print("=" * 60)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Plot 1: Rolling Coverage Rate ---
fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

# Dates for x-axis (use pandas DatetimeIndex)
plot_dates = oos_dates

for ax_idx, method_label in enumerate([('sc', 'Split Conformal'), ('ac', 'Adaptive Conformal')]):
    ax = axes[ax_idx]
    method_key, method_name = method_label

    for model_name, color in [('GJR', '#2196F3'), ('A4f', '#FF5722')]:
        rc = rolling_coverage[f"{model_name}_{method_key}"]
        valid_mask_rc = ~np.isnan(rc)
        if np.any(valid_mask_rc):
            ax.plot(plot_dates[valid_mask_rc], rc[valid_mask_rc],
                   label=model_name, color=color, linewidth=1.2, alpha=0.8)

    ax.axhline(y=0.90, color='gray', linestyle='--', linewidth=1, alpha=0.7, label='90% nominal')
    ax.set_ylabel('Rolling Coverage (126-day)')
    ax.set_title(f'{method_name} - Rolling Coverage Rate')
    ax.legend(loc='lower left')
    ax.set_ylim(0.6, 1.05)
    ax.grid(True, alpha=0.3)

axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
axes[-1].xaxis.set_major_locator(mdates.YearLocator())
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1055_coverage_plot.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1055_coverage_plot.png")

# --- Plot 2: Interval Width Comparison ---
fig, axes = plt.subplots(2, 1, figsize=(14, 10), sharex=True)

for ax_idx, model_name in enumerate(['GJR', 'A4f']):
    ax = axes[ax_idx]
    key = f"{model_name}_90"
    sc_widths = results[key]['_sc_widths']
    valid_w = ~np.isnan(sc_widths)

    if np.any(valid_w):
        ax.fill_between(plot_dates[valid_w], 0, sc_widths[valid_w],
                        alpha=0.5, color='#2196F3' if model_name == 'GJR' else '#FF5722',
                        label=f'{model_name} interval width')

    ax.set_ylabel('Interval Width')
    ax.set_title(f'{model_name} - 90% Split Conformal Interval Width')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

    # Add VIX on secondary axis
    ax2 = ax.twinx()
    ax2.plot(plot_dates, oos_vix, color='gray', alpha=0.3, linewidth=0.8, label='VIX')
    ax2.set_ylabel('VIX', color='gray')
    ax2.tick_params(axis='y', labelcolor='gray')

axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
axes[-1].xaxis.set_major_locator(mdates.YearLocator())
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1055_interval_width.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1055_interval_width.png")

# --- Plot 3: A4f vs GJR width side by side ---
fig, ax = plt.subplots(figsize=(14, 6))

key_gjr = "GJR_90"
key_a4f = "A4f_90"
gjr_w = results[key_gjr]['_sc_widths']
a4f_w = results[key_a4f]['_sc_widths']
both_w = ~np.isnan(gjr_w) & ~np.isnan(a4f_w)

if np.any(both_w):
    # Plot rolling mean of widths
    gjr_w_series = pd.Series(gjr_w, index=plot_dates).rolling(63, min_periods=30).mean()
    a4f_w_series = pd.Series(a4f_w, index=plot_dates).rolling(63, min_periods=30).mean()

    ax.plot(plot_dates, gjr_w_series, label='GJR (63-day avg)', color='#2196F3', linewidth=1.5)
    ax.plot(plot_dates, a4f_w_series, label='A4f (63-day avg)', color='#FF5722', linewidth=1.5)
    ax.fill_between(plot_dates,
                    gjr_w_series.fillna(0),
                    a4f_w_series.fillna(0),
                    where=(gjr_w_series > a4f_w_series),
                    alpha=0.2, color='#FF5722', label='A4f narrower')
    ax.fill_between(plot_dates,
                    gjr_w_series.fillna(0),
                    a4f_w_series.fillna(0),
                    where=(gjr_w_series <= a4f_w_series),
                    alpha=0.2, color='#2196F3', label='GJR narrower')

ax.set_ylabel('90% Interval Width (63-day rolling avg)')
ax.set_title('Conformal Prediction Interval Width: A4f vs GJR')
ax.legend(loc='upper left')
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax.xaxis.set_major_locator(mdates.YearLocator())
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1055_width_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1055_width_comparison.png")

# --- Plot 4: ACI alpha_t adaptation ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

for ax_idx, model_name in enumerate(['GJR', 'A4f']):
    ax = axes[ax_idx]
    key = f"{model_name}_90"
    alpha_t = results[key]['_ac_alpha_t']
    valid_a = ~np.isnan(alpha_t)

    if np.any(valid_a):
        ax.plot(plot_dates[valid_a], alpha_t[valid_a],
               color='#2196F3' if model_name == 'GJR' else '#FF5722',
               linewidth=0.8, alpha=0.7)

    ax.axhline(y=0.10, color='gray', linestyle='--', linewidth=1, alpha=0.7, label='Target alpha=0.10')
    ax.set_ylabel('Adaptive alpha_t')
    ax.set_title(f'{model_name} - ACI Adaptive Miscoverage Rate (alpha_t)')
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
axes[-1].xaxis.set_major_locator(mdates.YearLocator())
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1055_aci_adaptation.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k1055_aci_adaptation.png")


# ============================================================
# Save Results JSON
# ============================================================
print("\n" + "=" * 60)
print("SAVING RESULTS")
print("=" * 60)

# Clean results (remove numpy arrays)
clean_results = {}
for key, val in results.items():
    clean_results[key] = {k: v for k, v in val.items() if not k.startswith('_')}

total_time = time.time() - START_TIME

output = {
    'experiment_id': 'K1055',
    'title': 'Conformal Prediction Intervals for A4f vs GJR Volatility Forecasts',
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance',
    'asset': 'SPY',
    'data_period': f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{dates[oos_start_idx].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n_total),
    'n_oos': int(n_oos),
    'n_refits': int(refit_count),
    'config': {
        'training_window': WINDOW,
        'refit_every': REFIT_EVERY,
        'calibration_window': CALIB_WINDOW,
        'alpha_levels': ALPHA_LEVELS,
        'aci_gamma': ACI_GAMMA,
        'rolling_coverage_window': ROLLING_WINDOW,
        'bootstrap_reps': 10000,
        'random_seed': 42,
    },
    'qlike': {
        'GJR': float(qlike_gjr),
        'A4f': float(qlike_a4f),
        'improvement_pct': float((qlike_gjr - qlike_a4f) / qlike_gjr * 100),
    },
    'conformal_results': clean_results,
    'width_ratios': width_ratios,
    'regime_analysis': regime_results,
    'failure_detection': failure_analysis,
    'runtime_seconds': float(total_time),
    'references': [
        'Vovk, Gammerman, Shafer (2005). Algorithmic Learning in a Random World',
        'Lei, GSell, Rinaldo, Tibshirani, Wasserman (2018). Distribution-Free Predictive Inference',
        'Gibbs & Candes (2021). Adaptive Conformal Inference Under Distribution Shift',
        'Barber, Candes, Ramdas, Tibshirani (2023). Conformal Prediction Beyond Exchangeability',
        'Winkler (1972). A Decision-Theoretic Approach to Interval Estimation',
        'Patton (2011). Volatility Forecast Comparison Using Imperfect Volatility Proxies',
    ],
}

results_path = os.path.join(SCRIPT_DIR, 'k1055_results.json')
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Saved {results_path}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

print(f"\nQLIKE: A4f={qlike_a4f:.6f} vs GJR={qlike_gjr:.6f} (A4f improves {(qlike_gjr-qlike_a4f)/qlike_gjr*100:.2f}%)")

for alpha in ALPHA_LEVELS:
    nom = 1 - alpha
    print(f"\n{nom*100:.0f}% Coverage:")
    for method in ['split_conformal', 'adaptive_conformal']:
        gjr_cov = results[f"GJR_{nom*100:.0f}"][method]['coverage']
        a4f_cov = results[f"A4f_{nom*100:.0f}"][method]['coverage']
        gjr_w = results[f"GJR_{nom*100:.0f}"][method]['avg_width']
        a4f_w = results[f"A4f_{nom*100:.0f}"][method]['avg_width']
        gjr_wink = results[f"GJR_{nom*100:.0f}"][method]['winkler_score']
        a4f_wink = results[f"A4f_{nom*100:.0f}"][method]['winkler_score']

        print(f"  {method}:")
        print(f"    GJR: cov={gjr_cov:.4f}, width={gjr_w:.6f}, Winkler={gjr_wink:.6f}")
        print(f"    A4f: cov={a4f_cov:.4f}, width={a4f_w:.6f}, Winkler={a4f_wink:.6f}")
        print(f"    Width ratio (A4f/GJR): {a4f_w/gjr_w:.4f}")
        print(f"    Winkler ratio (A4f/GJR): {a4f_wink/gjr_wink:.4f}")

print(f"\nTotal runtime: {total_time:.0f}s")
print("\nDone!")
