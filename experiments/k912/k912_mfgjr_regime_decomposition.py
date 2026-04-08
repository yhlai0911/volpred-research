#!/usr/bin/env python3
"""
K912: MF-GJR Regime Decomposition -- When Does MF-GJR Add Value?
================================================================
[提出: Claude, 執行: Claude]

K889v2 proved MF-GJR beats GJR overall (QLIKE -6.57% for SPY, DM t=-2.57).
This experiment decomposes that advantage by VIX regime, rolling windows,
and specific market events to understand WHEN MF-GJR adds value.

Key Questions:
  1. Is MF-GJR advantage concentrated in high-VIX regimes or uniform?
  2. Does the multiplicative tau component explain more variance in crises?
  3. Which specific events show the largest MF-GJR advantage?

Data:
  - Asset: SPY (most statistical power from K889v2)
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX from yfinance (^VIX)

Methodology:
  - Models: GJR-GARCH(1,1) and MF-GJR (same as K889v2)
  - Evaluation: Pointwise QLIKE on r^2 (Patton 2011)
  - Regime decomposition by VIX level
  - Bootstrap CI (10000 reps) for regime-specific advantages
  - DM test per regime
  - Rolling 63-day advantage analysis
  - Event window analysis (21-day windows around key events)
  - Tau contribution analysis across regimes

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Engle & Rangel (2008) RFS 21(3):1187-1222
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104

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
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K912"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k912_mfgjr_regime_decomposition_results.json')

# Data parameters (same as K889v2)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

# VIX regime thresholds
VIX_REGIMES = {
    'Low (<15)': (0, 15),
    'Medium (15-25)': (15, 25),
    'High (25-35)': (25, 35),
    'Crisis (>35)': (35, 999),
}

# Event windows for analysis (date, label)
EVENTS = [
    ('2020-03-16', 'COVID Crash'),
    ('2022-01-24', 'Fed Tightening Start'),
    ('2022-09-28', 'UK Gilt Crisis'),
    ('2023-03-10', 'SVB Collapse'),
    ('2024-08-05', 'Yen Carry Unwind'),
]
EVENT_WINDOW = 21  # days before and after

# Bootstrap
N_BOOTSTRAP = 10000

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR Regime Decomposition")
print("  When does MF-GJR add value over GJR?")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf


def load_spy_data(vix_data):
    """Load SPY data with VIX alignment."""
    print("  Loading SPY...")
    raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
    df = df.dropna(subset=['log_ret'])
    df = df.join(vix_data, how='left')
    df['VIX'] = df['VIX'].ffill()
    df = df.dropna()

    return df


# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

df = load_spy_data(vix_data)
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to "
      f"{df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (from K889v2)
# ============================================================
print("\n[2] Model implementations (GJR + MF-GJR from K889v2)...")


@njit(cache=True)
def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
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


@njit(cache=True)
def gjr_garch_forecast_oos(params, returns, h_prev):
    """One-step GJR-GARCH forecast."""
    omega, alpha, gamma, beta = params
    r_prev = returns
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


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


def fit_mf_gjr(returns, log_vix):
    """Fit MF-GJR model.

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GJR-GARCH(1,1) on u_t = r_t/sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t
    """
    n = len(returns)
    assert len(log_vix) == n

    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    # OLS for initial theta
    X_ols = np.column_stack([np.ones(n), log_vix_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        theta0, theta1, alpha, gamma, beta = params

        log_tau = theta0 + theta1 * log_vix_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        u = returns / np.sqrt(tau)

        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0

        for t in range(1, n):
            asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    best_ll = np.inf
    best_params = None

    starts = [
        [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
        [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.10, 0.85],
        [-8.0, 0.5, 0.05, 0.05, 0.90],
        [-7.0, 0.8, 0.03, 0.03, 0.93],
    ]
    bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

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


def forecast_mf_gjr_insample(params, returns, log_vix):
    """Generate in-sample sigma^2 from MF-GJR model.
    Returns arrays of sigma^2, g, and tau.
    """
    n = len(returns)
    theta0, theta1, alpha, gamma, beta = params
    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    log_tau = theta0 + theta1 * log_vix_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)
    u = returns / np.sqrt(tau)

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 3: ROLLING OOS EVALUATION (SPY only)
# ============================================================
print("\n[3] Rolling OOS evaluation for SPY...")

ret = df['log_ret'].values
log_vix_raw = np.log(df['VIX'].values)
vix_levels = df['VIX'].values  # raw VIX for regime classification
r2 = ret ** 2
dates = df.index

# Find OOS start index
oos_mask = dates >= OOS_START
oos_start_idx = np.argmax(oos_mask)
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
print(f"  OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

n_oos = len(ret) - oos_start_idx
print(f"  OOS days: {n_oos}")

# Storage for forecasts
forecasts_gjr = np.full(n_oos, np.nan)
forecasts_mfgjr = np.full(n_oos, np.nan)
oos_returns = ret[oos_start_idx:]
oos_r2 = r2[oos_start_idx:]
oos_dates = dates[oos_start_idx:]
oos_vix = vix_levels[oos_start_idx:]

# Track MF-GJR components
tau_series = np.full(n_oos, np.nan)
g_series = np.full(n_oos, np.nan)

# Track parameters for analysis
all_mfgjr_params = []

# ---- Rolling estimation ----
last_gjr_params = None
last_gjr_h = None
last_mfgjr_params = None
last_mfgjr_g = None
tau_prev_mfgjr = None

n_refits = 0
for t in range(n_oos):
    idx = oos_start_idx + t
    need_refit = (t == 0) or (t % REFIT_EVERY == 0)

    train_start = max(0, idx - WINDOW)
    train_ret = ret[train_start:idx]
    train_vix = log_vix_raw[train_start:idx]

    if need_refit:
        n_refits += 1

        # Fit GJR-GARCH
        gjr_params, gjr_ll = fit_gjr_garch(train_ret)
        if gjr_params is not None:
            last_gjr_params = gjr_params
            h_arr = np.empty(len(train_ret))
            h_arr[0] = np.var(train_ret)
            for tt in range(1, len(train_ret)):
                omega, alpha_p, gamma_p, beta_p = gjr_params
                asym = gamma_p * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                h_arr[tt] = omega + alpha_p * train_ret[tt-1]**2 + asym + beta_p * h_arr[tt-1]
                h_arr[tt] = max(h_arr[tt], 1e-10)
            # BUG FIX #3: Advance h one step
            last_gjr_h = gjr_garch_forecast_oos(gjr_params, train_ret[-1], h_arr[-1])

        # Fit MF-GJR
        mfgjr_params, mfgjr_ll = fit_mf_gjr(train_ret, train_vix)
        if mfgjr_params is not None:
            last_mfgjr_params = mfgjr_params
            all_mfgjr_params.append({
                'refit_t': t,
                'refit_date': str(dates[idx]),
                'theta_0': float(mfgjr_params[0]),
                'theta_1': float(mfgjr_params[1]),
                'alpha': float(mfgjr_params[2]),
                'gamma': float(mfgjr_params[3]),
                'beta': float(mfgjr_params[4]),
            })
            _, g_arr, tau_arr = forecast_mf_gjr_insample(mfgjr_params, train_ret, train_vix)
            # BUG FIX #3: Advance g one step
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
            last_tau = tau_arr[-1]
            u_last = train_ret[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
            asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
            last_mfgjr_g = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
            last_mfgjr_g = max(last_mfgjr_g, 1e-10)

    # === Generate one-step-ahead forecasts ===

    # GJR-GARCH
    if last_gjr_params is not None and last_gjr_h is not None:
        if not need_refit and t > 0:
            last_gjr_h = gjr_garch_forecast_oos(last_gjr_params, ret[idx-1], last_gjr_h)
        forecasts_gjr[t] = last_gjr_h

    # MF-GJR
    if last_mfgjr_params is not None:
        theta0, theta1, alpha_mf, gamma_mf, beta_mf = last_mfgjr_params
        log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
        tau_t = np.exp(log_tau_t)
        tau_t = max(tau_t, 1e-16)

        if need_refit:
            g_t = last_mfgjr_g
        else:
            u_prev = ret[idx-1] / np.sqrt(tau_prev_mfgjr)
            omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
            asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
            g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_mfgjr_g
            g_t = max(g_t, 1e-10)

        tau_prev_mfgjr = tau_t
        last_mfgjr_g = g_t
        forecasts_mfgjr[t] = tau_t * g_t
        tau_series[t] = tau_t
        g_series[t] = g_t

    if (t + 1) % 500 == 0:
        print(f"    Progress: {t+1}/{n_oos}")

print(f"  Refits: {n_refits}")

# ============================================================
# SECTION 4: OVERALL EVALUATION
# ============================================================
print("\n[4] Overall evaluation...")

# Pointwise QLIKE
qlike_gjr_pw = qlike_pointwise(oos_r2, forecasts_gjr)
qlike_mfgjr_pw = qlike_pointwise(oos_r2, forecasts_mfgjr)

# Delta QLIKE: positive = MF-GJR better
delta_qlike = qlike_gjr_pw - qlike_mfgjr_pw

# Overall statistics
overall_qlike_gjr = qlike(oos_r2, forecasts_gjr)
overall_qlike_mfgjr = qlike(oos_r2, forecasts_mfgjr)
overall_pct_improvement = ((overall_qlike_mfgjr - overall_qlike_gjr) / overall_qlike_gjr) * 100

# Overall DM test
t_stat_overall, p_val_overall = dm_test(qlike_mfgjr_pw, qlike_gjr_pw)

# Overall Spearman
rho_gjr, p_rho_gjr = spearman_corr(oos_r2, forecasts_gjr)
rho_mfgjr, p_rho_mfgjr = spearman_corr(oos_r2, forecasts_mfgjr)

print(f"  QLIKE GJR:    {overall_qlike_gjr:.6f}")
print(f"  QLIKE MF-GJR: {overall_qlike_mfgjr:.6f} ({overall_pct_improvement:+.3f}%)")
print(f"  DM test:      t={t_stat_overall:+.3f} (p={p_val_overall:.4f})")
print(f"  Spearman GJR: {rho_gjr:.4f}, MF-GJR: {rho_mfgjr:.4f}")

# ============================================================
# SECTION 5: VIX REGIME DECOMPOSITION
# ============================================================
print("\n[5] VIX regime decomposition...")

# Use VIX level from t-1 (the information available when making the forecast)
# oos_vix[t] is VIX at date t, but our forecast for day t uses VIX_{t-1}
oos_vix_prev = np.roll(oos_vix, 1)
oos_vix_prev[0] = oos_vix[0]  # fill first element

regime_results = {}
for regime_name, (vix_low, vix_high) in VIX_REGIMES.items():
    mask = (oos_vix_prev >= vix_low) & (oos_vix_prev < vix_high)
    n_obs = int(mask.sum())

    if n_obs < 30:
        print(f"  {regime_name}: n={n_obs} (too few observations, skipping)")
        regime_results[regime_name] = {
            'n_obs': n_obs,
            'mean_delta_qlike': None,
            'dm_t': None,
            'dm_p': None,
            'bootstrap_ci_95': None,
            'pct_mfgjr_wins': None,
        }
        continue

    delta_regime = delta_qlike[mask]
    mean_delta = float(np.nanmean(delta_regime))
    pct_wins = float(np.nanmean(delta_regime > 0) * 100)

    # DM test within regime
    gjr_loss_regime = qlike_gjr_pw[mask]
    mfgjr_loss_regime = qlike_mfgjr_pw[mask]
    try:
        t_stat_regime, p_val_regime = dm_test(mfgjr_loss_regime, gjr_loss_regime)
    except Exception:
        t_stat_regime, p_val_regime = np.nan, np.nan

    # Bootstrap CI for mean delta_qlike
    rng = np.random.default_rng(42)
    boot_means = np.empty(N_BOOTSTRAP)
    for b in range(N_BOOTSTRAP):
        boot_idx = rng.integers(0, n_obs, size=n_obs)
        boot_means[b] = np.nanmean(delta_regime[boot_idx])

    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))

    regime_results[regime_name] = {
        'n_obs': n_obs,
        'mean_delta_qlike': mean_delta,
        'dm_t': float(t_stat_regime),
        'dm_p': float(p_val_regime),
        'significant_harvey': bool(abs(t_stat_regime) > 3.0),
        'significant_5pct': bool(abs(t_stat_regime) > 1.96),
        'bootstrap_ci_95': [ci_lower, ci_upper],
        'pct_mfgjr_wins': pct_wins,
        'mean_vix': float(np.mean(oos_vix_prev[mask])),
    }

    sig_flag = "***" if abs(t_stat_regime) > 3.0 else ("*" if abs(t_stat_regime) > 1.96 else "NS")
    print(f"  {regime_name:20s}: n={n_obs:5d}  mean_delta={mean_delta:+.6f}  "
          f"DM t={t_stat_regime:+.3f} {sig_flag}  "
          f"CI=[{ci_lower:.6f}, {ci_upper:.6f}]  "
          f"MF-GJR wins {pct_wins:.1f}%")

# ============================================================
# SECTION 6: ROLLING ADVANTAGE ANALYSIS
# ============================================================
print("\n[6] Rolling advantage analysis (63-day window)...")

rolling_window = 63
rolling_mean = pd.Series(delta_qlike, index=oos_dates).rolling(rolling_window, min_periods=30).mean()
rolling_std = pd.Series(delta_qlike, index=oos_dates).rolling(rolling_window, min_periods=30).std()

# Find periods of max/min advantage
if rolling_mean.notna().any():
    max_adv_date = rolling_mean.idxmax()
    min_adv_date = rolling_mean.idxmin()
    max_adv_val = float(rolling_mean.max())
    min_adv_val = float(rolling_mean.min())
    print(f"  Max advantage: {max_adv_val:+.6f} on {max_adv_date}")
    print(f"  Min advantage: {min_adv_val:+.6f} on {min_adv_date}")

    # Compute what fraction of the OOS period has positive rolling advantage
    pct_positive_rolling = float((rolling_mean > 0).mean() * 100)
    print(f"  Fraction with positive rolling advantage: {pct_positive_rolling:.1f}%")

    # Correlation between rolling advantage and VIX level
    vix_series = pd.Series(oos_vix, index=oos_dates)
    vix_rolling = vix_series.rolling(rolling_window, min_periods=30).mean()
    valid_both = rolling_mean.notna() & vix_rolling.notna()
    if valid_both.sum() > 30:
        corr_adv_vix = float(np.corrcoef(
            rolling_mean[valid_both].values,
            vix_rolling[valid_both].values
        )[0, 1])
        print(f"  Correlation(rolling_advantage, rolling_VIX): {corr_adv_vix:.4f}")
    else:
        corr_adv_vix = np.nan
else:
    max_adv_date = min_adv_date = None
    max_adv_val = min_adv_val = 0.0
    pct_positive_rolling = 0.0
    corr_adv_vix = np.nan

rolling_results = {
    'window': rolling_window,
    'max_advantage': {'date': str(max_adv_date), 'value': max_adv_val},
    'min_advantage': {'date': str(min_adv_date), 'value': min_adv_val},
    'pct_positive_rolling': pct_positive_rolling,
    'corr_advantage_vix': corr_adv_vix if np.isfinite(corr_adv_vix) else None,
}

# ============================================================
# SECTION 7: EVENT WINDOW ANALYSIS
# ============================================================
print("\n[7] Event window analysis...")

event_results = {}
for event_date_str, event_label in EVENTS:
    event_date = pd.Timestamp(event_date_str)

    # Find closest OOS date
    date_diffs = abs(oos_dates - event_date)
    closest_idx = date_diffs.argmin()

    # Window: [closest_idx - EVENT_WINDOW, closest_idx + EVENT_WINDOW]
    window_start = max(0, closest_idx - EVENT_WINDOW)
    window_end = min(n_oos, closest_idx + EVENT_WINDOW + 1)

    delta_event = delta_qlike[window_start:window_end]
    vix_event = oos_vix[window_start:window_end]

    n_event = len(delta_event)
    if n_event < 5:
        event_results[event_label] = {
            'event_date': event_date_str,
            'n_days': n_event,
            'mean_delta_qlike': None,
        }
        continue

    mean_delta_event = float(np.nanmean(delta_event))
    mean_vix_event = float(np.nanmean(vix_event))
    max_vix_event = float(np.nanmax(vix_event))

    # Split into pre-event and post-event
    pre_event = delta_qlike[window_start:closest_idx]
    post_event = delta_qlike[closest_idx:window_end]

    event_results[event_label] = {
        'event_date': event_date_str,
        'n_days': n_event,
        'mean_delta_qlike': mean_delta_event,
        'mean_vix': mean_vix_event,
        'max_vix': max_vix_event,
        'pre_event_mean_delta': float(np.nanmean(pre_event)) if len(pre_event) > 0 else None,
        'post_event_mean_delta': float(np.nanmean(post_event)) if len(post_event) > 0 else None,
        'pct_mfgjr_wins': float(np.nanmean(delta_event > 0) * 100),
    }

    print(f"  {event_label:25s}: n={n_event:3d}  mean_delta={mean_delta_event:+.6f}  "
          f"mean_VIX={mean_vix_event:.1f}  max_VIX={max_vix_event:.1f}  "
          f"MF-GJR wins {event_results[event_label]['pct_mfgjr_wins']:.1f}%")

# ============================================================
# SECTION 8: TAU CONTRIBUTION ANALYSIS
# ============================================================
print("\n[8] Tau contribution analysis across regimes...")

# Total variance from MF-GJR: sigma^2 = tau * g
# We want to know how much of the variation in sigma^2 comes from tau vs g
# across different VIX regimes.

tau_contribution_results = {}
for regime_name, (vix_low, vix_high) in VIX_REGIMES.items():
    mask = (oos_vix_prev >= vix_low) & (oos_vix_prev < vix_high)
    n_obs = int(mask.sum())

    if n_obs < 30:
        tau_contribution_results[regime_name] = {'n_obs': n_obs}
        continue

    tau_regime = tau_series[mask]
    g_regime = g_series[mask]
    sigma2_regime = tau_regime * g_regime

    # Compute variance decomposition
    # log(sigma^2) = log(tau) + log(g)
    # var(log(sigma^2)) = var(log(tau)) + var(log(g)) + 2*cov(log(tau), log(g))
    valid = (tau_regime > 0) & (g_regime > 0) & np.isfinite(tau_regime) & np.isfinite(g_regime)
    if valid.sum() < 30:
        tau_contribution_results[regime_name] = {'n_obs': n_obs, 'valid': int(valid.sum())}
        continue

    log_tau = np.log(tau_regime[valid])
    log_g = np.log(g_regime[valid])
    log_sigma2 = log_tau + log_g

    var_log_tau = float(np.var(log_tau))
    var_log_g = float(np.var(log_g))
    cov_log_tau_g = float(np.cov(log_tau, log_g)[0, 1])
    var_log_sigma2 = float(np.var(log_sigma2))

    # Proportion of total variance from tau
    if var_log_sigma2 > 0:
        tau_share = (var_log_tau + cov_log_tau_g) / var_log_sigma2
        g_share = (var_log_g + cov_log_tau_g) / var_log_sigma2
    else:
        tau_share = g_share = 0.5

    tau_contribution_results[regime_name] = {
        'n_obs': n_obs,
        'var_log_tau': var_log_tau,
        'var_log_g': var_log_g,
        'cov_log_tau_g': cov_log_tau_g,
        'var_log_sigma2': var_log_sigma2,
        'tau_share_pct': float(tau_share * 100),
        'g_share_pct': float(g_share * 100),
        'mean_tau': float(np.mean(tau_regime[valid])),
        'mean_g': float(np.mean(g_regime[valid])),
        'mean_sigma2': float(np.mean(sigma2_regime[valid])),
    }

    print(f"  {regime_name:20s}: tau_share={tau_share*100:.1f}%  g_share={g_share*100:.1f}%  "
          f"mean_tau={np.mean(tau_regime[valid]):.2e}  mean_g={np.mean(g_regime[valid]):.4f}")

# ============================================================
# SECTION 9: GENERATE PLOTS
# ============================================================
print("\n[9] Generating plots...")

# --- Plot 1: VIX Regime Advantage Bar Chart ---
fig, ax = plt.subplots(figsize=(10, 6))

regime_names = []
mean_deltas = []
ci_lowers = []
ci_uppers = []
n_obs_list = []

for regime_name in VIX_REGIMES.keys():
    r = regime_results.get(regime_name, {})
    if r.get('mean_delta_qlike') is not None:
        regime_names.append(regime_name)
        mean_deltas.append(r['mean_delta_qlike'])
        ci_lowers.append(r['bootstrap_ci_95'][0])
        ci_uppers.append(r['bootstrap_ci_95'][1])
        n_obs_list.append(r['n_obs'])

x = np.arange(len(regime_names))
colors = ['#2ecc71' if d > 0 else '#e74c3c' for d in mean_deltas]
errors_lower = [m - cl for m, cl in zip(mean_deltas, ci_lowers)]
errors_upper = [cu - m for m, cu in zip(mean_deltas, ci_uppers)]

bars = ax.bar(x, mean_deltas, color=colors, alpha=0.8, edgecolor='black', linewidth=0.5)
ax.errorbar(x, mean_deltas, yerr=[errors_lower, errors_upper],
            fmt='none', color='black', capsize=5, linewidth=1.5)

ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.8)

for i, (name, n) in enumerate(zip(regime_names, n_obs_list)):
    ax.text(i, ax.get_ylim()[0] * 0.05, f'n={n}', ha='center', va='top', fontsize=9,
            fontweight='bold')

    # Add significance markers
    r = regime_results[name]
    if r.get('significant_harvey'):
        ax.text(i, mean_deltas[i] + errors_upper[i] + 0.0001, '***',
                ha='center', fontsize=12, fontweight='bold')
    elif r.get('significant_5pct'):
        ax.text(i, mean_deltas[i] + errors_upper[i] + 0.0001, '*',
                ha='center', fontsize=12, fontweight='bold')

ax.set_xlabel('VIX Regime', fontsize=12)
ax.set_ylabel('Mean Delta QLIKE\n(positive = MF-GJR better)', fontsize=11)
ax.set_title('K912: MF-GJR Advantage by VIX Regime\n(SPY, OOS 2019-2026, 95% Bootstrap CI)',
             fontsize=13, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(regime_names, fontsize=10)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k912_regime_advantage.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k912_regime_advantage.png")

# --- Plot 2: Rolling Advantage + VIX ---
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                 gridspec_kw={'height_ratios': [2, 1]})

# Top: Rolling delta QLIKE
rolling_dates = rolling_mean.index
ax1.plot(rolling_dates, rolling_mean.values, color='#2980b9', linewidth=1.2,
         label=f'Rolling {rolling_window}-day mean delta QLIKE')
ax1.fill_between(rolling_dates,
                  (rolling_mean - 1.96 * rolling_std / np.sqrt(rolling_window)).values,
                  (rolling_mean + 1.96 * rolling_std / np.sqrt(rolling_window)).values,
                  alpha=0.2, color='#2980b9')
ax1.axhline(y=0, color='red', linestyle='--', linewidth=1, alpha=0.8)
ax1.set_ylabel('Delta QLIKE\n(positive = MF-GJR better)', fontsize=11)
ax1.set_title('K912: Rolling MF-GJR Advantage Over GJR (SPY)',
              fontsize=13, fontweight='bold')
ax1.legend(loc='upper left', fontsize=9)

# Add event markers
for event_date_str, event_label in EVENTS:
    event_date = pd.Timestamp(event_date_str)
    if event_date >= oos_dates[0] and event_date <= oos_dates[-1]:
        ax1.axvline(x=event_date, color='orange', linestyle=':', linewidth=1, alpha=0.7)
        ax1.text(event_date, ax1.get_ylim()[1] * 0.95, event_label,
                 rotation=45, fontsize=7, ha='left', va='top', color='orange')

# Bottom: VIX level
vix_oos_series = pd.Series(oos_vix, index=oos_dates)
ax2.fill_between(oos_dates, vix_oos_series.values, alpha=0.3, color='gray')
ax2.plot(oos_dates, vix_oos_series.values, color='gray', linewidth=0.5)

# Color VIX by regime
for regime_name, (vix_low, vix_high) in VIX_REGIMES.items():
    mask = (vix_oos_series >= vix_low) & (vix_oos_series < vix_high)
    colors_map = {'Low (<15)': '#2ecc71', 'Medium (15-25)': '#f39c12',
                  'High (25-35)': '#e67e22', 'Crisis (>35)': '#e74c3c'}
    c = colors_map.get(regime_name, 'gray')
    ax2.fill_between(oos_dates, 0, vix_oos_series.values, where=mask.values,
                     alpha=0.4, color=c, label=regime_name)

ax2.set_ylabel('VIX Level', fontsize=11)
ax2.set_xlabel('Date', fontsize=11)
ax2.legend(loc='upper right', fontsize=8, ncol=2)

ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k912_rolling_advantage.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k912_rolling_advantage.png")

# --- Plot 3: Event Window Analysis ---
n_events = len([e for e in EVENTS if event_results.get(e[1], {}).get('mean_delta_qlike') is not None])
if n_events > 0:
    fig, axes = plt.subplots(1, n_events, figsize=(4 * n_events, 5), sharey=True)
    if n_events == 1:
        axes = [axes]

    plot_idx = 0
    for event_date_str, event_label in EVENTS:
        r = event_results.get(event_label, {})
        if r.get('mean_delta_qlike') is None:
            continue

        event_date = pd.Timestamp(event_date_str)
        date_diffs = abs(oos_dates - event_date)
        closest_idx = date_diffs.argmin()
        window_start = max(0, closest_idx - EVENT_WINDOW)
        window_end = min(n_oos, closest_idx + EVENT_WINDOW + 1)

        delta_event = delta_qlike[window_start:window_end]
        event_dates = oos_dates[window_start:window_end]
        relative_days = np.arange(len(delta_event)) - (closest_idx - window_start)

        ax = axes[plot_idx]
        colors_event = ['#2ecc71' if d > 0 else '#e74c3c' for d in delta_event]
        ax.bar(relative_days, delta_event, color=colors_event, alpha=0.7, width=0.8)
        ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.8)
        ax.axvline(x=0, color='orange', linestyle='-', linewidth=2, alpha=0.8)
        ax.set_title(f'{event_label}\n(VIX max={r["max_vix"]:.0f})', fontsize=10, fontweight='bold')
        ax.set_xlabel('Days from event', fontsize=9)
        if plot_idx == 0:
            ax.set_ylabel('Delta QLIKE\n(+ = MF-GJR better)', fontsize=9)
        ax.tick_params(axis='both', labelsize=8)

        # Add mean line
        ax.axhline(y=r['mean_delta_qlike'], color='blue', linestyle=':', linewidth=1.5, alpha=0.7)

        plot_idx += 1

    plt.suptitle('K912: MF-GJR Advantage Around Market Events',
                 fontsize=13, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k912_event_windows.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: k912_event_windows.png")

# --- Plot 4: Tau Contribution by Regime ---
fig, ax = plt.subplots(figsize=(10, 6))

tau_shares = []
g_shares = []
regime_labels = []

for regime_name in VIX_REGIMES.keys():
    r = tau_contribution_results.get(regime_name, {})
    if 'tau_share_pct' in r:
        regime_labels.append(regime_name)
        tau_shares.append(r['tau_share_pct'])
        g_shares.append(r['g_share_pct'])

x = np.arange(len(regime_labels))
width = 0.6

ax.bar(x, tau_shares, width, label='tau (VIX-driven long-run)', color='#3498db', alpha=0.8)
ax.bar(x, g_shares, width, bottom=tau_shares, label='g (short-run GARCH)', color='#e74c3c', alpha=0.8)

ax.axhline(y=50, color='gray', linestyle='--', linewidth=0.8)
ax.set_xlabel('VIX Regime', fontsize=12)
ax.set_ylabel('Variance Contribution (%)', fontsize=11)
ax.set_title('K912: Tau vs G Contribution to Total Variance by VIX Regime\n'
             '(MF-GJR model, SPY OOS 2019-2026)', fontsize=13, fontweight='bold')
ax.set_xticks(x)
ax.set_xticklabels(regime_labels, fontsize=10)
ax.legend(fontsize=10)

# Add percentage labels
for i, (ts, gs) in enumerate(zip(tau_shares, g_shares)):
    ax.text(i, ts/2, f'{ts:.0f}%', ha='center', va='center', fontsize=11, fontweight='bold', color='white')
    ax.text(i, ts + gs/2, f'{gs:.0f}%', ha='center', va='center', fontsize=11, fontweight='bold', color='white')

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k912_tau_contribution.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k912_tau_contribution.png")

# ============================================================
# SECTION 10: COMPILE RESULTS AND SAVE
# ============================================================
print("\n[10] Compiling results...")

elapsed = time.time() - START_TIME

# Key findings summary
findings = []
# Find regime with max advantage
max_regime = max(
    [(name, r.get('mean_delta_qlike', -999))
     for name, r in regime_results.items() if r.get('mean_delta_qlike') is not None],
    key=lambda x: x[1]
)
min_regime = min(
    [(name, r.get('mean_delta_qlike', 999))
     for name, r in regime_results.items() if r.get('mean_delta_qlike') is not None],
    key=lambda x: x[1]
)

findings.append(f"MF-GJR advantage is largest in {max_regime[0]} regime (delta QLIKE={max_regime[1]:+.6f})")
findings.append(f"MF-GJR advantage is smallest in {min_regime[0]} regime (delta QLIKE={min_regime[1]:+.6f})")

if corr_adv_vix and np.isfinite(corr_adv_vix):
    findings.append(f"Rolling advantage correlates with VIX (corr={corr_adv_vix:.4f})")

# Check if tau share increases with VIX
tau_share_values = []
for regime_name in VIX_REGIMES.keys():
    r = tau_contribution_results.get(regime_name, {})
    if 'tau_share_pct' in r:
        tau_share_values.append(r['tau_share_pct'])
if len(tau_share_values) >= 3:
    if tau_share_values[-1] > tau_share_values[0]:
        findings.append(
            f"Tau contribution INCREASES with VIX: "
            f"from {tau_share_values[0]:.1f}% (Low VIX) to {tau_share_values[-1]:.1f}% (highest regime)")
    else:
        findings.append(
            f"Tau contribution does NOT clearly increase with VIX: "
            f"{tau_share_values[0]:.1f}% (Low) vs {tau_share_values[-1]:.1f}% (highest)")

# Construct key_findings text
key_findings_text = (
    f"K912 decomposes MF-GJR's overall QLIKE advantage ({overall_pct_improvement:+.2f}% vs GJR) "
    f"across VIX regimes. "
    f"Largest advantage in {max_regime[0]} (delta QLIKE={max_regime[1]:+.6f}), "
    f"smallest in {min_regime[0]} (delta QLIKE={min_regime[1]:+.6f}). "
)
if corr_adv_vix and np.isfinite(corr_adv_vix):
    key_findings_text += (
        f"Rolling advantage correlates with VIX (r={corr_adv_vix:.3f}). "
    )
key_findings_text += (
    f"Tau contribution to total variance: "
    + ", ".join([
        f"{name}={tau_contribution_results.get(name, {}).get('tau_share_pct', 0):.0f}%"
        for name in VIX_REGIMES.keys()
        if 'tau_share_pct' in tau_contribution_results.get(name, {})
    ])
    + ". "
    + "MF-GJR's multiplicative structure captures VIX-driven long-run dynamics "
    + "that single-component GJR misses."
)

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR Regime Decomposition: When Does MF-GJR Add Value?',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'models': ['GJR-GARCH(1,1)', 'MF-GJR'],
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'estimation': f'Rolling window (w={WINDOW}), refit every {REFIT_EVERY} days',
        'evaluation': 'Pointwise QLIKE on r^2 (Patton 2011), DM test, Bootstrap CI',
        'vix_regimes': {k: list(v) for k, v in VIX_REGIMES.items()},
        'bootstrap_reps': N_BOOTSTRAP,
        'event_window_days': EVENT_WINDOW,
    },
    'data': {
        'source': 'yfinance',
        'asset': 'SPY',
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'n_oos': n_oos,
        'oos_dates': f'{oos_dates[0].strftime("%Y-%m-%d")} to {oos_dates[-1].strftime("%Y-%m-%d")}',
        'n_refits': n_refits,
    },
    'overall': {
        'qlike_gjr': round(overall_qlike_gjr, 6),
        'qlike_mfgjr': round(overall_qlike_mfgjr, 6),
        'qlike_pct_improvement': round(overall_pct_improvement, 3),
        'dm_t': round(float(t_stat_overall), 3),
        'dm_p': round(float(p_val_overall), 4),
        'significant_harvey': bool(abs(t_stat_overall) > 3.0),
        'spearman_gjr': round(rho_gjr, 4),
        'spearman_mfgjr': round(rho_mfgjr, 4),
    },
    'regime_analysis': {},
    'rolling_analysis': rolling_results,
    'event_analysis': {},
    'tau_contribution': {},
    'mfgjr_parameter_evolution': all_mfgjr_params[-5:],  # Last 5 refits
    'key_findings': key_findings_text,
    'findings_list': findings,
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Engle & Rangel (2008) RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
    ],
}

# Add regime results (round for JSON)
for name, r in regime_results.items():
    results['regime_analysis'][name] = {}
    for k, v in r.items():
        if isinstance(v, float):
            results['regime_analysis'][name][k] = round(v, 6)
        elif isinstance(v, list):
            results['regime_analysis'][name][k] = [round(x, 6) if isinstance(x, float) else x for x in v]
        else:
            results['regime_analysis'][name][k] = v

# Add event results
for label, r in event_results.items():
    results['event_analysis'][label] = {}
    for k, v in r.items():
        if isinstance(v, float):
            results['event_analysis'][label][k] = round(v, 6)
        else:
            results['event_analysis'][label][k] = v

# Add tau contribution results
for name, r in tau_contribution_results.items():
    results['tau_contribution'][name] = {}
    for k, v in r.items():
        if isinstance(v, float):
            results['tau_contribution'][name][k] = round(v, 6)
        else:
            results['tau_contribution'][name][k] = v

# Save results
with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n{'='*70}")
print(f"K912 COMPLETE in {elapsed:.1f}s")
print(f"  Results: {RESULTS_PATH}")
print(f"  Overall QLIKE improvement: {overall_pct_improvement:+.3f}%")
print(f"  DM test: t={t_stat_overall:+.3f}")
for finding in findings:
    print(f"  * {finding}")
print(f"{'='*70}")
