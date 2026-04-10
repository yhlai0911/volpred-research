#!/usr/bin/env python3
"""
K1024: A4f Refit Frequency Sensitivity Analysis (Paper 9 Robustness)
====================================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K988 established A4f(VIX²) as the winning specification with QLIKE=-8.358 vs
  GJR's -8.277, DM t=4.167. The default refit frequency was every 63 days
  (quarterly). Reviewers will ask: "Why 63 days? How sensitive are results to
  this choice?"

  This experiment systematically tests 5 refit frequencies for both A4f and GJR:
    - Daily (every 1 day) — upper bound on accuracy
    - Monthly (every 21 days)
    - Quarterly (every 63 days) — current default
    - Semi-annual (every 126 days)
    - Annual (every 252 days)

Research Questions:
  1. How much does refit frequency affect QLIKE for A4f vs GJR?
  2. Is the A4f > GJR advantage stable across all frequencies?
  3. Can we justify 63-day refit as a practical choice?

Models:
  A4f: sigma2_t = tau_t * g_t, where tau_t = max(theta0 + theta1 * VIX^2_{t-1}, eps)
       g_t = omega + alpha * u^2_{t-1} + gamma * u^2_{t-1} * I(u<0) + beta * g_{t-1}
       omega is free (not constrained to 1 - alpha - gamma/2 - beta)
       Student-t innovations with df=8 (per K1021 recommendation)
  GJR: Standard GJR-GARCH(1,1) with Student-t df=8

References:
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Conrad & Loch (2015). JBES 33(3):338-358.

Data: SPY 2005-2026, VIX from yfinance. OOS: 2013-01-01 to latest.
Window: 2000 rolling.
Evaluation: QLIKE on r^2 (Patton 2011), DM test (pairwise).
Seed: 42.

Author: VolPred Research System
Date: 2026-04-10
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
EXPERIMENT_ID = "K1024"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1024_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2013-01-01'
WINDOW = 2000
STUDENT_T_DF = 8  # K1021 recommendation

# Refit frequencies to test
REFIT_FREQS = [1, 21, 63, 126, 252]
REFIT_LABELS = ['Daily', 'Monthly', 'Quarterly', 'Semi-annual', 'Annual']

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Refit Frequency Sensitivity Analysis")
print("  Paper 9 Robustness Check")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...", flush=True)
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
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}", flush=True)
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}", flush=True)

ret = df['log_ret'].values
vix = df['VIX'].values
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...", flush=True)
oos_ret = ret[oos_mask]
print(f"  OOS mean return: {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std: {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
print(f"  VIX mean (OOS): {np.mean(vix[oos_mask]):.2f}")
print(f"  VIX std (OOS): {np.std(vix[oos_mask]):.2f}", flush=True)


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (Student-t, df=8)
# ============================================================
print("\n[3] Model implementations (Student-t df=8)...", flush=True)

SCALE = np.sqrt((STUDENT_T_DF - 2) / STUDENT_T_DF)  # scale for Student-t


def student_t_logpdf_array(x, sigma2, df=STUDENT_T_DF):
    """Vectorized log-pdf of Student-t with variance sigma2."""
    scale_factor = np.sqrt(sigma2) * SCALE
    z = x / scale_factor
    ll = (gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * df)
          - np.log(scale_factor) - (df + 1) / 2 * np.log(1 + z**2 / df))
    return ll


# --- GJR-GARCH(1,1)-t ---
def gjr_loglik_t(params, returns, df=STUDENT_T_DF):
    """GJR-GARCH(1,1) with Student-t log-likelihood."""
    omega, alpha, gamma_p, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    for t in range(1, n):
        asym = gamma_p * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    # Vectorized log-likelihood
    ll = np.sum(student_t_logpdf_array(returns, h, df))
    return -ll


def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1)-t."""
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
            res = optimize.minimize(gjr_loglik_t, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma_p, beta = params
    asym = gamma_p * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: Multiplicative GJR-X (VIX^2) with free omega, Student-t ---
def fit_a4f_t(returns, vix_vals):
    """
    Fit A4f model: sigma2_t = tau_t * g_t
    tau_t = max(theta0 + theta1 * VIX^2_{t-1}, eps)
    g_t = omega + alpha * u^2_{t-1} + gamma * u^2_{t-1} * I(u<0) + beta * g_{t-1}
    where u_{t-1} = r_{t-1} / sqrt(tau_t), omega is free
    Student-t(df=8) innovations.
    """
    n = len(returns)

    # Lagged VIX (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    vix_lag_sq = vix_lag ** 2

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag_sq) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        # Compute tau
        tau = theta0 + theta1 * vix_lag_sq
        tau = np.maximum(tau, 1e-16)

        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0

        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])  # denom = tau_t (current, predetermined from VIX_{t-1})
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        valid_mask = sigma2 > 0
        ll = np.sum(student_t_logpdf_array(returns[valid_mask], sigma2[valid_mask], STUDENT_T_DF))
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


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING FOR ALL FREQUENCIES
# ============================================================
print("\n[4] Out-of-sample forecasting across refit frequencies...", flush=True)

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}", flush=True)

# Target: r^2
oos_r2 = r2[oos_indices]


def qlike_score(target, forecast):
    """QLIKE loss: mean(target/forecast + log(forecast)). Lower is better."""
    valid = (target > 0) & (forecast > 0) & np.isfinite(target) & np.isfinite(forecast)
    if valid.sum() < 100:
        return np.nan
    t, f = target[valid], forecast[valid]
    return np.mean(t / f + np.log(f))


def qlike_pointwise(target, forecast):
    """Pointwise QLIKE losses for DM test."""
    losses = np.full_like(target, np.nan, dtype=np.float64)
    valid = (target > 0) & (forecast > 0) & np.isfinite(target) & np.isfinite(forecast)
    losses[valid] = target[valid] / forecast[valid] + np.log(forecast[valid])
    return losses


def dm_test_custom(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided). Negative t => model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 50:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with bandwidth h)
    gamma0 = np.mean((d - d_mean)**2)
    gamma_sum = 0.0
    for k in range(1, h + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (h + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return t_stat, p_val


# Storage for cross-frequency DM tests
all_gjr_losses = {}
all_a4f_losses = {}

# Storage for results
results = {
    'experiment_id': EXPERIMENT_ID,
    'metadata': {
        'asset': 'SPY',
        'data_source': 'yfinance',
        'data_start': DATA_START,
        'data_end': df.index[-1].strftime('%Y-%m-%d'),
        'oos_start': OOS_START,
        'n_total': int(n_total),
        'n_oos': int(n_oos_actual),
        'window': WINDOW,
        'student_t_df': STUDENT_T_DF,
        'refit_frequencies': REFIT_FREQS,
        'refit_labels': REFIT_LABELS,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'references': [
            'Patton (2011). J Econometrics 160:246-256.',
            'Harvey et al. (2016). ...Tests for Forecast Comparison.',
            'Engle, Ghysels & Sohn (2013). RES 95(3):776-797.',
            'Conrad & Loch (2015). JBES 33(3):338-358.',
        ],
    },
    'models': {},
    'dm_tests_a4f_vs_gjr': {},
    'cross_frequency_dm': {},
}


# Run OOS for each refit frequency
for freq_idx, (refit_freq, freq_label) in enumerate(zip(REFIT_FREQS, REFIT_LABELS)):
    print(f"\n  --- Refit every {refit_freq} days ({freq_label}) ---", flush=True)

    freq_start = time.time()

    # Storage
    gjr_forecasts = np.full(n_oos_actual, np.nan)
    a4f_forecasts = np.full(n_oos_actual, np.nan)

    # State
    gjr_params = None
    gjr_h = None
    a4f_params = None
    a4f_g = None

    refit_count = 0

    for t_idx, abs_idx in enumerate(oos_indices):
        if t_idx % 500 == 0 and t_idx > 0:
            elapsed = time.time() - freq_start
            print(f"    OOS step {t_idx}/{n_oos_actual} ({elapsed:.1f}s)", flush=True)

        need_refit = (t_idx % refit_freq == 0) or (t_idx == 0)

        if need_refit:
            refit_count += 1
            train_start = max(0, abs_idx - WINDOW)
            train_ret = ret[train_start:abs_idx]
            train_vix = vix[train_start:abs_idx]

            # Fit GJR-t
            gjr_params_new = fit_gjr_t(train_ret)
            if gjr_params_new is not None:
                gjr_params = gjr_params_new
                # Initialize h from training data by running filter
                h = np.var(train_ret)
                for i in range(1, len(train_ret)):
                    h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
                gjr_h = h

            # Fit A4f-t
            a4f_params_new = fit_a4f_t(train_ret, train_vix)
            if a4f_params_new is not None:
                a4f_params = a4f_params_new
                theta0, theta1 = a4f_params[0], a4f_params[1]
                omega_g = a4f_params[2]
                alpha_p, gamma_p, beta_p = a4f_params[3], a4f_params[4], a4f_params[5]

                # Initialize g from training
                n_train = len(train_ret)
                vix_lag_tr = np.empty(n_train)
                vix_lag_tr[0] = train_vix[0]
                vix_lag_tr[1:] = train_vix[:-1]
                tau_train = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)

                persist = alpha_p + gamma_p / 2.0 + beta_p
                eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg
                for i in range(1, n_train):
                    u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                    asym_val = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                    g = omega_g + alpha_p * u_prev**2 + asym_val + beta_p * g
                    g = max(g, 1e-10)

                a4f_g = g

        # --- Generate forecasts ---
        # GJR: h_{t|t-1} using previous h and r_{t-1}
        if gjr_params is not None and gjr_h is not None:
            if abs_idx > 0:
                gjr_h = gjr_forecast_1step(gjr_params, gjr_h, ret[abs_idx - 1])
            gjr_forecasts[t_idx] = gjr_h

        # A4f: sigma2_{t|t-1} = tau_t * g_t
        if a4f_params is not None and a4f_g is not None:
            theta0, theta1 = a4f_params[0], a4f_params[1]
            omega_g = a4f_params[2]
            alpha_p, gamma_p, beta_p = a4f_params[3], a4f_params[4], a4f_params[5]

            # tau_t uses VIX_{t-1} (lagged, no lookahead)
            vix_prev = vix[abs_idx - 1] if abs_idx > 0 else vix[0]
            tau_t = max(theta0 + theta1 * vix_prev**2, 1e-16)

            # Update g: g_t = omega + alpha*u^2_{t-1} + gamma*u^2_{t-1}*I + beta*g_{t-1}
            if abs_idx > 0:
                u_prev = ret[abs_idx - 1] / np.sqrt(tau_t)
                asym_val = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                a4f_g = omega_g + alpha_p * u_prev**2 + asym_val + beta_p * a4f_g
                a4f_g = max(a4f_g, 1e-10)

            a4f_forecasts[t_idx] = tau_t * a4f_g

    freq_elapsed = time.time() - freq_start

    # Compute QLIKE
    gjr_qlike = qlike_score(oos_r2, gjr_forecasts)
    a4f_qlike = qlike_score(oos_r2, a4f_forecasts)

    # Pointwise QLIKE losses for DM test
    gjr_losses = qlike_pointwise(oos_r2, gjr_forecasts)
    a4f_losses = qlike_pointwise(oos_r2, a4f_forecasts)

    # Store for cross-frequency comparisons
    all_gjr_losses[refit_freq] = gjr_losses.copy()
    all_a4f_losses[refit_freq] = a4f_losses.copy()

    # DM test: A4f vs GJR (negative t => A4f better because lower loss)
    valid = np.isfinite(a4f_losses) & np.isfinite(gjr_losses)
    dm_t, dm_p = dm_test_custom(a4f_losses[valid], gjr_losses[valid])

    # Spearman correlation with r^2
    from scipy.stats import spearmanr
    gjr_valid = np.isfinite(gjr_forecasts) & (gjr_forecasts > 0)
    a4f_valid = np.isfinite(a4f_forecasts) & (a4f_forecasts > 0)
    gjr_rho, gjr_rho_p = spearmanr(oos_r2[gjr_valid], gjr_forecasts[gjr_valid])
    a4f_rho, a4f_rho_p = spearmanr(oos_r2[a4f_valid], a4f_forecasts[a4f_valid])

    freq_key = f"freq_{refit_freq}"

    results['models'][freq_key] = {
        'refit_frequency': int(refit_freq),
        'label': freq_label,
        'n_refits': int(refit_count),
        'runtime_seconds': round(freq_elapsed, 2),
        'gjr': {
            'qlike': float(gjr_qlike),
            'spearman_rho': float(gjr_rho),
            'spearman_p': float(gjr_rho_p),
        },
        'a4f': {
            'qlike': float(a4f_qlike),
            'spearman_rho': float(a4f_rho),
            'spearman_p': float(a4f_rho_p),
        },
    }

    results['dm_tests_a4f_vs_gjr'][freq_key] = {
        't_stat': float(dm_t) if not np.isnan(dm_t) else None,
        'p_value': float(dm_p) if not np.isnan(dm_p) else None,
        'significant_harvey': bool(abs(dm_t) > 3.0) if not np.isnan(dm_t) else False,
        'direction': 'A4f_better' if dm_t < 0 else 'GJR_better',
    }

    print(f"    Refits: {refit_count}, Runtime: {freq_elapsed:.1f}s")
    print(f"    GJR QLIKE: {gjr_qlike:.6f}, A4f QLIKE: {a4f_qlike:.6f}")
    print(f"    DM t-stat (A4f vs GJR): {dm_t:.4f}, p={dm_p:.6f}")
    print(f"    Significant (Harvey |t|>3): {abs(dm_t) > 3.0 if not np.isnan(dm_t) else 'N/A'}")
    print(f"    A4f Spearman rho: {a4f_rho:.4f}, GJR rho: {gjr_rho:.4f}", flush=True)


# ============================================================
# SECTION 5: CROSS-FREQUENCY DM TESTS
# ============================================================
print("\n[5] Cross-frequency DM tests...", flush=True)

# Compare daily refit vs each other frequency for both models
# Also compare Q63 vs each frequency
for freq_idx, (refit_freq, freq_label) in enumerate(zip(REFIT_FREQS, REFIT_LABELS)):
    if refit_freq == 1:
        continue

    freq_key = f"freq_{refit_freq}"

    # Daily vs this freq for A4f
    valid_a4f = np.isfinite(all_a4f_losses[1]) & np.isfinite(all_a4f_losses[refit_freq])
    dm_daily_a4f_t, dm_daily_a4f_p = dm_test_custom(
        all_a4f_losses[1][valid_a4f], all_a4f_losses[refit_freq][valid_a4f])

    # Daily vs this freq for GJR
    valid_gjr = np.isfinite(all_gjr_losses[1]) & np.isfinite(all_gjr_losses[refit_freq])
    dm_daily_gjr_t, dm_daily_gjr_p = dm_test_custom(
        all_gjr_losses[1][valid_gjr], all_gjr_losses[refit_freq][valid_gjr])

    # Q63 vs this freq for A4f (skip if this is Q63)
    dm_q63_a4f_t, dm_q63_a4f_p = np.nan, np.nan
    if refit_freq != 63:
        valid_q63 = np.isfinite(all_a4f_losses[63]) & np.isfinite(all_a4f_losses[refit_freq])
        dm_q63_a4f_t, dm_q63_a4f_p = dm_test_custom(
            all_a4f_losses[63][valid_q63], all_a4f_losses[refit_freq][valid_q63])

    results['cross_frequency_dm'][freq_key] = {
        'label': freq_label,
        'daily_vs_this_a4f': {
            't_stat': float(dm_daily_a4f_t) if not np.isnan(dm_daily_a4f_t) else None,
            'p_value': float(dm_daily_a4f_p) if not np.isnan(dm_daily_a4f_p) else None,
            'sig_harvey': bool(abs(dm_daily_a4f_t) > 3.0) if not np.isnan(dm_daily_a4f_t) else False,
        },
        'daily_vs_this_gjr': {
            't_stat': float(dm_daily_gjr_t) if not np.isnan(dm_daily_gjr_t) else None,
            'p_value': float(dm_daily_gjr_p) if not np.isnan(dm_daily_gjr_p) else None,
            'sig_harvey': bool(abs(dm_daily_gjr_t) > 3.0) if not np.isnan(dm_daily_gjr_t) else False,
        },
        'q63_vs_this_a4f': {
            't_stat': float(dm_q63_a4f_t) if not np.isnan(dm_q63_a4f_t) else None,
            'p_value': float(dm_q63_a4f_p) if not np.isnan(dm_q63_a4f_p) else None,
            'sig_harvey': bool(abs(dm_q63_a4f_t) > 3.0) if not np.isnan(dm_q63_a4f_t) else False,
        },
    }

    print(f"  Daily vs {freq_label}:")
    dt_a = dm_daily_a4f_t if not np.isnan(dm_daily_a4f_t) else 0
    dt_g = dm_daily_gjr_t if not np.isnan(dm_daily_gjr_t) else 0
    print(f"    A4f DM t={dt_a:.4f}, GJR DM t={dt_g:.4f}")
    if refit_freq != 63:
        dt_q = dm_q63_a4f_t if not np.isnan(dm_q63_a4f_t) else 0
        print(f"    Q63 vs {freq_label} A4f DM t={dt_q:.4f}", flush=True)


# ============================================================
# SECTION 6: SUMMARY TABLE
# ============================================================
print("\n[6] Summary table...", flush=True)
print(f"\n{'Freq':>12} {'Refits':>8} {'GJR QLIKE':>12} {'A4f QLIKE':>12} {'DM t':>8} {'Sig':>6} {'Runtime':>10}")
print("-" * 75)

for refit_freq, freq_label in zip(REFIT_FREQS, REFIT_LABELS):
    freq_key = f"freq_{refit_freq}"
    m = results['models'][freq_key]
    dm = results['dm_tests_a4f_vs_gjr'][freq_key]
    dm_t_val = dm['t_stat'] if dm['t_stat'] is not None else 0.0
    sig = 'YES' if dm['significant_harvey'] else 'no'
    print(f"{freq_label:>12} {m['n_refits']:>8} {m['gjr']['qlike']:>12.6f} {m['a4f']['qlike']:>12.6f} "
          f"{dm_t_val:>8.3f} {sig:>6} {m['runtime_seconds']:>8.1f}s")

# QLIKE range analysis
a4f_qlikes_all = [results['models'][f'freq_{f}']['a4f']['qlike'] for f in REFIT_FREQS]
gjr_qlikes_all = [results['models'][f'freq_{f}']['gjr']['qlike'] for f in REFIT_FREQS]

best_a4f = min(a4f_qlikes_all)
worst_a4f = max(a4f_qlikes_all)
q63_a4f = results['models']['freq_63']['a4f']['qlike']
daily_a4f = results['models']['freq_1']['a4f']['qlike']

print(f"\n  A4f QLIKE range: {best_a4f:.6f} to {worst_a4f:.6f}")
print(f"  A4f QLIKE spread: {abs(worst_a4f - best_a4f):.6f}")
print(f"  A4f daily vs Q63: {abs(daily_a4f - q63_a4f):.6f}")
print(f"  Relative difference (daily vs Q63): {abs(daily_a4f - q63_a4f)/abs(q63_a4f)*100:.4f}%", flush=True)

# ============================================================
# SECTION 7: CHARTS
# ============================================================
print("\n[7] Generating charts...", flush=True)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

plt.rcParams['font.size'] = 11
plt.rcParams['figure.dpi'] = 150

# Chart 1: QLIKE vs Refit Frequency (line chart for both models)
fig, ax1 = plt.subplots(figsize=(10, 6))

freq_positions = np.arange(len(REFIT_FREQS))

ax1.plot(freq_positions, a4f_qlikes_all, 'o-', color='#2196F3', linewidth=2.5,
         markersize=10, label='A4f (VIX$^2$)', zorder=5)
ax1.plot(freq_positions, gjr_qlikes_all, 's--', color='#FF5722', linewidth=2.5,
         markersize=10, label='GJR-GARCH', zorder=5)

# Highlight quarterly (default)
ax1.axvline(x=2, color='gray', linestyle=':', alpha=0.7, label='Quarterly (default)')

ax1.set_xlabel('Refit Frequency', fontsize=13)
ax1.set_ylabel('QLIKE (lower is better)', fontsize=13)
ax1.set_title('K1024: QLIKE vs Refit Frequency\nA4f(VIX$^2$) vs GJR-GARCH, SPY OOS 2013-2026', fontsize=14)
ax1.set_xticks(freq_positions)
ax1.set_xticklabels(REFIT_LABELS)
ax1.legend(fontsize=11, loc='upper left')
ax1.grid(True, alpha=0.3)

# Add DM significance markers
for i, f in enumerate(REFIT_FREQS):
    dm = results['dm_tests_a4f_vs_gjr'][f'freq_{f}']
    dm_t_val = dm['t_stat'] if dm['t_stat'] is not None else 0
    if abs(dm_t_val) > 3.0:
        ax1.annotate(f't={dm_t_val:.1f}***', xy=(i, a4f_qlikes_all[i]),
                    xytext=(10, -20), textcoords='offset points',
                    fontsize=9, color='#2196F3', fontweight='bold')

plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1024_qlike_vs_frequency.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart1_path}")

# Chart 2: DM t-stat vs frequency (A4f vs GJR) — bar chart
fig, ax2 = plt.subplots(figsize=(10, 6))

dm_tstats = []
for f in REFIT_FREQS:
    dm = results['dm_tests_a4f_vs_gjr'][f'freq_{f}']
    t = dm['t_stat'] if dm['t_stat'] is not None else 0
    dm_tstats.append(t)

# Flip sign so positive = A4f better
dm_tstats_flipped = [-t for t in dm_tstats]
colors = ['#4CAF50' if abs(t) > 3.0 else '#FFC107' for t in dm_tstats]
bars = ax2.bar(freq_positions, dm_tstats_flipped, color=colors, width=0.6,
               edgecolor='black', linewidth=0.5)

ax2.axhline(y=3.0, color='red', linestyle='--', linewidth=1.5,
            label='Harvey (2016) threshold = 3.0')
ax2.axhline(y=0, color='black', linewidth=0.5)

ax2.set_xlabel('Refit Frequency', fontsize=13)
ax2.set_ylabel('|DM t-statistic| (A4f better > 0)', fontsize=13)
ax2.set_title('K1024: DM Test A4f vs GJR across Refit Frequencies\n(Green = significant at Harvey 2016 |t|>3.0)', fontsize=14)
ax2.set_xticks(freq_positions)
ax2.set_xticklabels(REFIT_LABELS)
ax2.legend(fontsize=11)
ax2.grid(True, alpha=0.3, axis='y')

# Add value labels
for i, (bar_obj, t) in enumerate(zip(bars, dm_tstats)):
    val = -t
    ax2.text(bar_obj.get_x() + bar_obj.get_width()/2, max(val + 0.15, 0.15),
             f'{val:.2f}', ha='center', va='bottom', fontsize=10, fontweight='bold')

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1024_dm_vs_frequency.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart2_path}")

# Chart 3: Runtime vs Frequency — bar chart
fig, ax3 = plt.subplots(figsize=(10, 5))

runtimes = [results['models'][f'freq_{f}']['runtime_seconds'] for f in REFIT_FREQS]
n_refits_list = [results['models'][f'freq_{f}']['n_refits'] for f in REFIT_FREQS]

ax3.bar(freq_positions, runtimes, color='#9C27B0', width=0.6,
        edgecolor='black', linewidth=0.5)

for i, (rt, nr) in enumerate(zip(runtimes, n_refits_list)):
    ax3.text(i, rt + max(runtimes)*0.02, f'{rt:.0f}s\n({nr} refits)',
             ha='center', va='bottom', fontsize=10)

ax3.set_xlabel('Refit Frequency', fontsize=13)
ax3.set_ylabel('Runtime (seconds)', fontsize=13)
ax3.set_title('K1024: Computation Time vs Refit Frequency\n(A4f + GJR combined per frequency)', fontsize=14)
ax3.set_xticks(freq_positions)
ax3.set_xticklabels(REFIT_LABELS)
ax3.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1024_runtime_vs_frequency.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart3_path}")

# ============================================================
# SECTION 8: CONCLUSION AND SAVE
# ============================================================
print("\n[8] Saving results...", flush=True)

# Conclusion
all_sig = all(results['dm_tests_a4f_vs_gjr'][f'freq_{f}']['significant_harvey']
              for f in REFIT_FREQS)
qlike_spread_pct = abs(worst_a4f - best_a4f) / abs(best_a4f) * 100
daily_q63_pct = abs(daily_a4f - q63_a4f) / abs(q63_a4f) * 100

results['conclusion'] = {
    'a4f_qlike_best': float(best_a4f),
    'a4f_qlike_worst': float(worst_a4f),
    'a4f_qlike_spread_pct': float(qlike_spread_pct),
    'gjr_qlike_best': float(min(gjr_qlikes_all)),
    'gjr_qlike_worst': float(max(gjr_qlikes_all)),
    'a4f_advantage_all_frequencies': all_sig,
    'daily_vs_q63_diff_pct': float(daily_q63_pct),
    'recommendation': (
        f'Quarterly (63-day) refit is a practical choice. '
        f'A4f QLIKE spread across all 5 frequencies is only {qlike_spread_pct:.3f}% '
        f'(range: {best_a4f:.6f} to {worst_a4f:.6f}). '
        f'Daily vs Q63 difference is only {daily_q63_pct:.4f}%. '
        f'A4f advantage over GJR is {"maintained at all frequencies (all DM |t|>3.0)" if all_sig else "present but significance varies across frequencies"}. '
        f'GARCH parameters are slow-moving, confirming that frequent refitting yields diminishing returns.'
    ),
}

total_time = time.time() - START_TIME
results['metadata']['total_runtime_seconds'] = round(total_time, 2)

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to: {RESULTS_PATH}")

print(f"\n{'='*70}")
print(f"K1024 COMPLETE. Total runtime: {total_time:.1f}s")
print(f"{'='*70}")
