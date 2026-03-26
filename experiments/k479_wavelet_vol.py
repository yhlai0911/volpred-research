#!/usr/bin/env python3
"""
K479: Wavelet Decomposition for Volatility Prediction

Background:
  K111: Wavelet decomposition on r² — GARCH dominated all frequency bands (0/9 significant).
        But K111 compared Wavelet vs GARCH, not Wavelet-HAR vs standard HAR.
  K465/K469: HAR (1d/5d/21d) is genuinely superior to GJR-GARCH (8/10 cross-OOS).
        HAR success = multi-scale time aggregation works.
  → This experiment: Can wavelet frequency decomposition improve upon HAR's
    ad-hoc time aggregation (1d/5d/21d)?

Research Questions:
  1. Do wavelet-decomposed vol components have different predictive power?
  2. Is the low-frequency component (trend) better at predicting future vol?
  3. Does Wavelet-HAR outperform standard HAR?

Wavelet Method:
  DWT (Discrete Wavelet Transform) on |returns| using db4 wavelet, 4 levels:
    D1: 1-2 day cycles (high frequency noise)
    D2: 2-4 day cycles
    D3: 4-8 day cycles (weekly pattern)
    D4: 8-16 day cycles
    A4: 16+ day cycles (low frequency trend)

  For each rolling window (252 days), compute DWT → extract energy at each scale
  → use as predictors for next-day realized volatility.

Models:
  1. Lagged RV21 (baseline: rolling 21-day variance)
  2. HAR (1d + 5d + 21d lagged RV) — current best
  3. Wavelet-HAR: D1_energy, D2_energy, D3_energy, D4_energy, A4_energy as regressors
  4. Low-freq only: A4 component energy → future vol
  5. High-freq only: D1+D2 energy → future vol
  6. Combined: HAR + A4 (augmented HAR)

Asset: SPY
OOS: 2023-01-01 to 2025-12-31
IS: 2000 trading days before OOS start
DWT window: 252 days (rolling, within IS for coefficient estimation)

Data: yfinance (SPY), 2005-01-01 to present
Evaluation: QLIKE with r² proxy (avoiding Parkinson tautology per K468)
Statistical test: Diebold-Mariano

References:
  Gençay et al. (2002) "Differentiating intraday seasonalities through wavelet
    multi-scaling" Physica A
  In & Kim (2006) "The hedge ratio and the empirical performance of the wavelet-based
    hedging strategy" JBFA
  Barunik et al. (2016) "Asymmetric volatility connectedness on the forex market"
    J. International Money and Finance
  Corsi (2009) J Financial Econometrics — HAR-RV model
  K111, K465, K469 — prior wavelet and HAR experiments

Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
import pywt
from datetime import datetime, timezone
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K479: Wavelet Decomposition for Volatility Prediction")
print("  Wavelet-HAR vs standard HAR — principled frequency decomposition")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
DWT_WAVELET = 'db4'
DWT_LEVEL = 4
DWT_WINDOW = 252  # 1 year of trading days for DWT
IS_WINDOW = 2000  # In-sample for regression estimation
OOS_START = '2023-01-01'
OOS_END = '2025-12-31'

# ============================================================
# Data Download
# ============================================================
print("\n[1/6] Downloading SPY data...")
t0 = time.time()
spy = yf.download('SPY', start='2005-01-01', end='2026-03-26', auto_adjust=True, progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy = spy.dropna(subset=['Close', 'High', 'Low'])

# Compute returns and volatility proxies
spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = np.abs(spy['log_ret'])
spy['r_squared'] = spy['log_ret'] ** 2  # r² proxy for evaluation
spy['log_range'] = np.log(spy['High'] / spy['Low'])
spy['parkinson_var'] = spy['log_range'] ** 2 / (4 * np.log(2))
spy = spy.dropna()

print(f"  SPY: {len(spy)} obs, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  Download time: {time.time() - t0:.1f}s")

# ============================================================
# Diagnostics
# ============================================================
print("\n[2/6] Data diagnostics...")
abs_ret = spy['abs_ret'].values
r2 = spy['r_squared'].values

adf_result = adfuller(abs_ret, maxlag=20)
lb_result = acorr_ljungbox(abs_ret, lags=[10], return_df=True)

diagnostics = {
    'n_obs': len(spy),
    'date_range': f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
    'abs_ret_mean': float(np.mean(abs_ret)),
    'abs_ret_std': float(np.std(abs_ret)),
    'abs_ret_skew': float(stats.skew(abs_ret)),
    'abs_ret_kurt': float(stats.kurtosis(abs_ret)),
    'r2_mean': float(np.mean(r2)),
    'r2_std': float(np.std(r2)),
    'adf_stat': float(adf_result[0]),
    'adf_p': float(adf_result[1]),
    'is_stationary': bool(adf_result[1] < 0.05),
    'ljung_box_p_10': float(lb_result['lb_pvalue'].values[0]),
    'has_autocorrelation': bool(lb_result['lb_pvalue'].values[0] < 0.05),
}

print(f"  |ret| mean={diagnostics['abs_ret_mean']:.6f}, std={diagnostics['abs_ret_std']:.6f}")
print(f"  |ret| skew={diagnostics['abs_ret_skew']:.2f}, kurt={diagnostics['abs_ret_kurt']:.2f}")
print(f"  r² mean={diagnostics['r2_mean']:.8f}")
print(f"  ADF stat={diagnostics['adf_stat']:.3f}, p={diagnostics['adf_p']:.2e} → {'Stationary' if diagnostics['is_stationary'] else 'Non-stationary'}")
print(f"  Ljung-Box(10) p={diagnostics['ljung_box_p_10']:.2e} → {'Autocorrelated' if diagnostics['has_autocorrelation'] else 'No autocorrelation'}")

# ============================================================
# Wavelet Feature Extraction
# ============================================================
print("\n[3/6] Computing wavelet features (rolling DWT)...")
t1 = time.time()

def compute_wavelet_energy(series, wavelet='db4', level=4):
    """
    Compute energy at each DWT scale for a given series.
    Returns dict with D1_energy, D2_energy, ..., D{level}_energy, A{level}_energy.
    Energy = mean of squared coefficients, scaled to approximate variance contribution.
    """
    coeffs = pywt.wavedec(np.ascontiguousarray(series, dtype=np.float64), wavelet, level=level)
    # coeffs = [cA_level, cD_level, cD_{level-1}, ..., cD_1]
    energies = {}
    # Approximation (low freq trend)
    energies[f'A{level}_energy'] = float(np.mean(coeffs[0] ** 2))
    # Detail coefficients (high to low freq)
    for i in range(1, len(coeffs)):
        detail_level = level - i + 1
        energies[f'D{detail_level}_energy'] = float(np.mean(coeffs[i] ** 2))
    return energies


def reconstruct_components(series, wavelet='db4', level=4):
    """
    Reconstruct each wavelet component in the time domain.
    Returns dict of arrays, each the same length as the input.
    """
    coeffs = pywt.wavedec(np.ascontiguousarray(series, dtype=np.float64), wavelet, level=level)
    n = len(series)
    components = {}

    for i in range(len(coeffs)):
        # Zero out all coefficients except the i-th
        c = [np.zeros_like(c) for c in coeffs]
        c[i] = coeffs[i]
        rec = pywt.waverec(c, wavelet)
        components[i] = rec[:n]  # Trim to original length

    return components


# Rolling wavelet features for the entire dataset
n = len(spy)
feature_names = [f'D{i}_energy' for i in range(1, DWT_LEVEL + 1)] + [f'A{DWT_LEVEL}_energy']

# Pre-allocate feature arrays
wavelet_features = {name: np.full(n, np.nan) for name in feature_names}

# Also compute reconstructed low-freq and high-freq vol
low_freq_vol = np.full(n, np.nan)  # A4 component variance
high_freq_vol = np.full(n, np.nan)  # D1+D2 component variance

for t in range(DWT_WINDOW, n):
    window = abs_ret[t - DWT_WINDOW:t].copy()  # copy to avoid read-only buffer

    # Energy features
    energies = compute_wavelet_energy(window, DWT_WAVELET, DWT_LEVEL)
    for name in feature_names:
        wavelet_features[name][t] = energies[name]

    # Reconstruct components for low/high freq vol
    components = reconstruct_components(window, DWT_WAVELET, DWT_LEVEL)
    # Low freq = A4 (index 0 in coeffs)
    low_freq_vol[t] = np.var(components[0])
    # High freq = D1 (last in coeffs list) + D2 (second to last)
    hf = components[len(components) - 1] + components[len(components) - 2]
    high_freq_vol[t] = np.var(hf)

# Add features to dataframe
for name in feature_names:
    spy[name] = wavelet_features[name]
spy['low_freq_vol'] = low_freq_vol
spy['high_freq_vol'] = high_freq_vol

print(f"  Wavelet feature computation: {time.time() - t1:.1f}s")
print(f"  Features computed for {np.sum(~np.isnan(wavelet_features['D1_energy']))} days")

# ============================================================
# HAR Features
# ============================================================
print("\n[4/6] Computing HAR features...")
spy['rv1'] = spy['r_squared']  # daily RV = r²
spy['rv5'] = spy['r_squared'].rolling(5).mean()  # weekly
spy['rv21'] = spy['r_squared'].rolling(21).mean()  # monthly

# Target: next-day r² (for prediction)
spy['target_r2'] = spy['r_squared'].shift(-1)

# Drop NaN rows
feature_cols = feature_names + ['low_freq_vol', 'high_freq_vol', 'rv1', 'rv5', 'rv21']
spy_clean = spy.dropna(subset=feature_cols + ['target_r2']).copy()
print(f"  Clean dataset: {len(spy_clean)} obs")

# ============================================================
# Wavelet Feature Analysis
# ============================================================
print("\n  --- Wavelet Energy Distribution ---")
energy_cols = feature_names
total_energy = spy_clean[energy_cols].sum(axis=1)
for col in energy_cols:
    pct = (spy_clean[col] / total_energy).mean() * 100
    corr_with_target = spy_clean[col].corr(spy_clean['target_r2'])
    ac1 = spy_clean[col].autocorr(lag=1)
    print(f"  {col:15s}: {pct:5.1f}% of energy, corr(target)={corr_with_target:.4f}, AC(1)={ac1:.3f}")

print(f"\n  low_freq_vol  corr(target)={spy_clean['low_freq_vol'].corr(spy_clean['target_r2']):.4f}")
print(f"  high_freq_vol corr(target)={spy_clean['high_freq_vol'].corr(spy_clean['target_r2']):.4f}")
print(f"  rv21          corr(target)={spy_clean['rv21'].corr(spy_clean['target_r2']):.4f}")

# ============================================================
# OOS Evaluation
# ============================================================
print("\n[5/6] OOS evaluation (2023-2025)...")
t2 = time.time()

# Define OOS period
oos_mask = (spy_clean.index >= OOS_START) & (spy_clean.index <= OOS_END)
oos_data = spy_clean[oos_mask].copy()
n_oos = len(oos_data)
print(f"  OOS: {oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')}, {n_oos} obs")

# IS data: everything before OOS
is_data = spy_clean[spy_clean.index < OOS_START].copy()
n_is = len(is_data)
print(f"  IS: {is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')}, {n_is} obs")

if n_is < IS_WINDOW:
    print(f"  WARNING: IS ({n_is}) < IS_WINDOW ({IS_WINDOW}), using all available IS data")


def fit_ols(X, y):
    """Simple OLS: y = X @ beta + epsilon. Returns beta."""
    # Add constant
    X_const = np.column_stack([np.ones(len(X)), X])
    try:
        beta = np.linalg.lstsq(X_const, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_const.shape[1])
    return beta


def predict_ols(X, beta):
    """Predict using OLS coefficients."""
    X_const = np.column_stack([np.ones(len(X)), X])
    return X_const @ beta


def qlike(forecast, realized):
    """QLIKE loss: realized/forecast - log(realized/forecast) - 1.
    Lower = better. Requires forecast > 0 and realized > 0."""
    valid = (forecast > 0) & (realized > 0)
    f = forecast[valid]
    r = realized[valid]
    ratio = r / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def qlike_log(forecast, realized):
    """QLIKE in log form for comparison: log(forecast) + realized/forecast.
    Lower = better."""
    valid = (forecast > 0) & (realized > 0)
    f = forecast[valid]
    r = realized[valid]
    return float(np.mean(np.log(f) + r / f))


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Negative t → model 1 better. Positive t → model 2 better."""
    d = loss1 - loss2
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    T = len(d)
    gamma0 = np.var(d, ddof=1)
    if h > 1:
        for k in range(1, h):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            gamma0 += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(gamma0 / T)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=T - 1))
    return float(t_stat), float(p_value)


# ---- Rolling OOS forecasts ----
# Use expanding window from IS_WINDOW to match K469 methodology
# For each OOS day, re-estimate on all available IS data

# Prepare arrays
is_X_har = is_data[['rv1', 'rv5', 'rv21']].values
is_X_wavelet = is_data[feature_names].values
is_X_lowfreq = is_data[['low_freq_vol']].values
is_X_highfreq = is_data[['high_freq_vol']].values
is_X_combined = is_data[['rv1', 'rv5', 'rv21', f'A{DWT_LEVEL}_energy']].values
is_y = is_data['target_r2'].values

oos_X_har = oos_data[['rv1', 'rv5', 'rv21']].values
oos_X_wavelet = oos_data[feature_names].values
oos_X_lowfreq = oos_data[['low_freq_vol']].values
oos_X_highfreq = oos_data[['high_freq_vol']].values
oos_X_combined = oos_data[['rv1', 'rv5', 'rv21', f'A{DWT_LEVEL}_energy']].values
oos_y = oos_data['target_r2'].values

# Model definitions
models = {
    'rv21_baseline': {
        'description': 'Lagged RV21 (rolling 21-day variance)',
        'X_is': is_data[['rv21']].values,
        'X_oos': oos_data[['rv21']].values,
    },
    'har': {
        'description': 'HAR (1d+5d+21d) — standard multi-scale',
        'X_is': is_X_har,
        'X_oos': oos_X_har,
    },
    'wavelet_har': {
        'description': 'Wavelet-HAR: D1-D4 + A4 energy as regressors',
        'X_is': is_X_wavelet,
        'X_oos': oos_X_wavelet,
    },
    'low_freq_only': {
        'description': 'Low-freq only: A4 component variance',
        'X_is': is_X_lowfreq,
        'X_oos': oos_X_lowfreq,
    },
    'high_freq_only': {
        'description': 'High-freq only: D1+D2 component variance',
        'X_is': is_X_highfreq,
        'X_oos': oos_X_highfreq,
    },
    'har_plus_wavelet': {
        'description': 'HAR + A4_energy (augmented HAR)',
        'X_is': is_X_combined,
        'X_oos': oos_X_combined,
    },
}

# --- Method 1: Static IS estimation (fit once on full IS, forecast OOS) ---
print("\n  --- Static IS estimation ---")
results_static = {}

for model_name, model_info in models.items():
    X_is = model_info['X_is']
    X_oos = model_info['X_oos']

    # Fit on IS
    beta = fit_ols(X_is, is_y)

    # Predict OOS
    forecast = predict_ols(X_oos, beta)
    forecast = np.maximum(forecast, 1e-10)  # Floor at small positive

    # Evaluate
    ql = qlike(forecast, oos_y)
    ql_log = qlike_log(forecast, oos_y)

    # Store individual losses for DM test
    valid = (forecast > 0) & (oos_y > 0)
    individual_losses = np.log(forecast[valid]) + oos_y[valid] / forecast[valid]

    results_static[model_name] = {
        'description': model_info['description'],
        'qlike': ql,
        'qlike_log': ql_log,
        'beta': beta.tolist(),
        'n_params': len(beta),
        'losses': individual_losses,
    }

    print(f"  {model_name:20s}: QLIKE_log={ql_log:.6f}, QLIKE={ql:.6f}, params={len(beta)}")

# --- Method 2: Rolling IS estimation (re-estimate every 63 days) ---
print("\n  --- Rolling estimation (re-estimate every 63 days) ---")
results_rolling = {}

# Combine IS and OOS for rolling
all_data = spy_clean.copy()
oos_start_idx = all_data.index.get_loc(oos_data.index[0])

for model_name, model_info in models.items():
    forecasts = []
    actuals = []
    individual_losses = []

    # Feature column names for extraction
    if model_name == 'rv21_baseline':
        feat_cols = ['rv21']
    elif model_name == 'har':
        feat_cols = ['rv1', 'rv5', 'rv21']
    elif model_name == 'wavelet_har':
        feat_cols = feature_names
    elif model_name == 'low_freq_only':
        feat_cols = ['low_freq_vol']
    elif model_name == 'high_freq_only':
        feat_cols = ['high_freq_vol']
    elif model_name == 'har_plus_wavelet':
        feat_cols = ['rv1', 'rv5', 'rv21', f'A{DWT_LEVEL}_energy']

    last_beta = None
    refit_interval = 63  # quarterly re-estimation

    for i in range(n_oos):
        t_idx = oos_start_idx + i

        # Re-estimate every refit_interval days
        if i % refit_interval == 0 or last_beta is None:
            # Use all data up to current point for IS
            is_end_idx = t_idx
            is_start_idx = max(0, is_end_idx - IS_WINDOW)

            is_slice = all_data.iloc[is_start_idx:is_end_idx]
            X_is_roll = is_slice[feat_cols].values
            y_is_roll = is_slice['target_r2'].values

            # Remove NaN
            valid_mask = ~np.isnan(y_is_roll) & ~np.any(np.isnan(X_is_roll), axis=1)
            if np.sum(valid_mask) < 50:
                continue
            last_beta = fit_ols(X_is_roll[valid_mask], y_is_roll[valid_mask])

        # Forecast
        X_t = all_data.iloc[t_idx:t_idx+1][feat_cols].values
        if np.any(np.isnan(X_t)):
            continue

        fc = predict_ols(X_t, last_beta)[0]
        fc = max(fc, 1e-10)
        actual = oos_y[i]

        if actual > 0:
            forecasts.append(fc)
            actuals.append(actual)
            loss = np.log(fc) + actual / fc
            individual_losses.append(loss)

    forecasts = np.array(forecasts)
    actuals = np.array(actuals)
    individual_losses = np.array(individual_losses)

    ql = qlike(forecasts, actuals)
    ql_log = float(np.mean(individual_losses))

    results_rolling[model_name] = {
        'description': model_info['description'],
        'qlike': ql,
        'qlike_log': ql_log,
        'n_forecasts': len(forecasts),
        'losses': individual_losses,
    }

    print(f"  {model_name:20s}: QLIKE_log={ql_log:.6f}, QLIKE={ql:.6f}, n={len(forecasts)}")

# ============================================================
# DM Tests
# ============================================================
print("\n[6/6] Diebold-Mariano tests...")

# Use rolling results for DM tests
print("\n  --- Static estimation DM tests ---")
dm_results_static = {}
reference_models = ['har', 'rv21_baseline']

for ref in reference_models:
    if ref not in results_static:
        continue
    ref_losses = results_static[ref]['losses']
    for model_name in results_static:
        if model_name == ref:
            continue
        model_losses = results_static[model_name]['losses']
        # Align lengths
        min_len = min(len(ref_losses), len(model_losses))
        t_stat, p_val = dm_test(ref_losses[:min_len], model_losses[:min_len])

        key = f"{ref}_vs_{model_name}"
        direction = f"{ref} better" if t_stat < 0 else f"{model_name} better"
        significant = p_val < 0.05
        dm_results_static[key] = {
            't_stat': t_stat,
            'p_value': p_val,
            'significant': significant,
            'direction': direction,
        }
        marker = '*' if significant else ' '
        print(f"  {marker} {ref} vs {model_name}: t={t_stat:.3f}, p={p_val:.4f} → {direction}")

print("\n  --- Rolling estimation DM tests ---")
dm_results_rolling = {}

for ref in reference_models:
    if ref not in results_rolling:
        continue
    ref_losses = results_rolling[ref]['losses']
    for model_name in results_rolling:
        if model_name == ref:
            continue
        model_losses = results_rolling[model_name]['losses']
        min_len = min(len(ref_losses), len(model_losses))
        t_stat, p_val = dm_test(ref_losses[:min_len], model_losses[:min_len])

        key = f"{ref}_vs_{model_name}"
        direction = f"{ref} better" if t_stat < 0 else f"{model_name} better"
        significant = p_val < 0.05
        dm_results_rolling[key] = {
            't_stat': t_stat,
            'p_value': p_val,
            'significant': significant,
            'direction': direction,
        }
        marker = '*' if significant else ' '
        print(f"  {marker} {ref} vs {model_name}: t={t_stat:.3f}, p={p_val:.4f} → {direction}")

# ============================================================
# Wavelet Component Analysis
# ============================================================
print("\n  --- Wavelet Component Predictive Content ---")
# For each scale, compute the incremental R² when added to a baseline

from numpy.linalg import lstsq

def compute_r2(X, y):
    """Compute R² from OLS regression."""
    X_const = np.column_stack([np.ones(len(X)), X])
    beta = lstsq(X_const, y, rcond=None)[0]
    y_hat = X_const @ beta
    ss_res = np.sum((y - y_hat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2)
    return 1 - ss_res / ss_tot

# IS R² analysis
print("\n  In-sample R² for next-day r²:")
r2_baseline = compute_r2(is_data[['rv21']].values, is_y)
print(f"    RV21 baseline:       R²={r2_baseline:.6f}")

r2_har = compute_r2(is_X_har, is_y)
print(f"    HAR (1d+5d+21d):     R²={r2_har:.6f}")

r2_wavelet = compute_r2(is_X_wavelet, is_y)
print(f"    Wavelet-HAR (5 scales): R²={r2_wavelet:.6f}")

r2_combined = compute_r2(is_X_combined, is_y)
print(f"    HAR + A4:            R²={r2_combined:.6f}")

r2_lowfreq = compute_r2(is_X_lowfreq, is_y)
print(f"    Low-freq only:       R²={r2_lowfreq:.6f}")

r2_highfreq = compute_r2(is_X_highfreq, is_y)
print(f"    High-freq only:      R²={r2_highfreq:.6f}")

# Individual wavelet scale R²
print("\n  Individual scale R²:")
for col in feature_names:
    r2_scale = compute_r2(is_data[[col]].values, is_y)
    print(f"    {col:15s}: R²={r2_scale:.6f}")

# ============================================================
# Rankings
# ============================================================
print("\n  === FINAL RANKINGS (QLIKE_log, lower=better) ===")
print("\n  Static estimation:")
ranking_static = sorted(results_static.items(), key=lambda x: x[1]['qlike_log'])
for rank, (name, res) in enumerate(ranking_static, 1):
    print(f"    {rank}. {name:20s}: {res['qlike_log']:.6f}")

print("\n  Rolling estimation:")
ranking_rolling = sorted(results_rolling.items(), key=lambda x: x[1]['qlike_log'])
for rank, (name, res) in enumerate(ranking_rolling, 1):
    print(f"    {rank}. {name:20s}: {res['qlike_log']:.6f}")

# Best wavelet vs HAR comparison
har_qlike_static = results_static['har']['qlike_log']
best_wavelet_name_static = None
best_wavelet_qlike_static = float('inf')
for name in ['wavelet_har', 'low_freq_only', 'high_freq_only', 'har_plus_wavelet']:
    if results_static[name]['qlike_log'] < best_wavelet_qlike_static:
        best_wavelet_qlike_static = results_static[name]['qlike_log']
        best_wavelet_name_static = name

har_qlike_rolling = results_rolling['har']['qlike_log']
best_wavelet_name_rolling = None
best_wavelet_qlike_rolling = float('inf')
for name in ['wavelet_har', 'low_freq_only', 'high_freq_only', 'har_plus_wavelet']:
    if results_rolling[name]['qlike_log'] < best_wavelet_qlike_rolling:
        best_wavelet_qlike_rolling = results_rolling[name]['qlike_log']
        best_wavelet_name_rolling = name

pct_diff_static = (best_wavelet_qlike_static - har_qlike_static) / abs(har_qlike_static) * 100
pct_diff_rolling = (best_wavelet_qlike_rolling - har_qlike_rolling) / abs(har_qlike_rolling) * 100

print(f"\n  === KEY COMPARISON ===")
print(f"  Static: HAR QLIKE_log={har_qlike_static:.6f}")
print(f"  Static: Best wavelet ({best_wavelet_name_static}) QLIKE_log={best_wavelet_qlike_static:.6f}")
print(f"  Static: Diff = {pct_diff_static:+.3f}%")
print(f"  Rolling: HAR QLIKE_log={har_qlike_rolling:.6f}")
print(f"  Rolling: Best wavelet ({best_wavelet_name_rolling}) QLIKE_log={best_wavelet_qlike_rolling:.6f}")
print(f"  Rolling: Diff = {pct_diff_rolling:+.3f}%")

# ============================================================
# Sub-period Analysis
# ============================================================
print("\n  === Sub-period Analysis ===")
sub_periods = [
    ('2023 (low vol)', '2023-01-01', '2023-12-31'),
    ('2024 (mixed)', '2024-01-01', '2024-12-31'),
    ('2025 (current)', '2025-01-01', '2025-12-31'),
]

sub_period_results = {}
for period_name, p_start, p_end in sub_periods:
    mask = (oos_data.index >= p_start) & (oos_data.index <= p_end)
    if mask.sum() < 20:
        continue

    sub_y = oos_y[mask.values if hasattr(mask, 'values') else mask]
    sub_results = {}

    for model_name in results_static:
        # Re-forecast for sub-period using static betas
        beta = np.array(results_static[model_name]['beta'])

        if model_name == 'rv21_baseline':
            feat_cols = ['rv21']
        elif model_name == 'har':
            feat_cols = ['rv1', 'rv5', 'rv21']
        elif model_name == 'wavelet_har':
            feat_cols = feature_names
        elif model_name == 'low_freq_only':
            feat_cols = ['low_freq_vol']
        elif model_name == 'high_freq_only':
            feat_cols = ['high_freq_vol']
        elif model_name == 'har_plus_wavelet':
            feat_cols = ['rv1', 'rv5', 'rv21', f'A{DWT_LEVEL}_energy']

        X_sub = oos_data.loc[mask, feat_cols].values
        fc = predict_ols(X_sub, beta)
        fc = np.maximum(fc, 1e-10)
        ql = qlike_log(fc, sub_y)
        sub_results[model_name] = ql

    sub_period_results[period_name] = sub_results
    ranking = sorted(sub_results.items(), key=lambda x: x[1])
    print(f"\n  {period_name} (n={mask.sum()}):")
    for rank, (name, ql) in enumerate(ranking, 1):
        print(f"    {rank}. {name:20s}: QLIKE_log={ql:.6f}")

# ============================================================
# Conclusion
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Determine if wavelet improves on HAR
har_wins_static = best_wavelet_qlike_static >= har_qlike_static
har_wins_rolling = best_wavelet_qlike_rolling >= har_qlike_rolling

# Check DM test for HAR vs best wavelet
dm_key = f"har_vs_{best_wavelet_name_static}"
if dm_key in dm_results_static:
    dm_sig = dm_results_static[dm_key]['significant']
    dm_dir = dm_results_static[dm_key]['direction']
else:
    dm_sig = False
    dm_dir = "N/A"

if har_wins_static and har_wins_rolling:
    conclusion = "HAR's ad-hoc multi-scale aggregation is at least as good as principled wavelet decomposition. The specific scales (1d/5d/21d) in HAR already capture the relevant multi-scale structure. Confirms K111: frequency decomposition does not improve vol prediction."
elif not har_wins_static and not har_wins_rolling:
    conclusion = f"Wavelet decomposition ({best_wavelet_name_static}) improves upon HAR! The principled frequency-domain approach captures structure missed by HAR's fixed 1d/5d/21d aggregation."
else:
    conclusion = "Mixed results: wavelet helps in one estimation method but not the other. No clear advantage."

print(f"\n  1. HAR wins static: {har_wins_static}")
print(f"  2. HAR wins rolling: {har_wins_rolling}")
print(f"  3. DM test (HAR vs best wavelet): {dm_dir}, significant={dm_sig}")
print(f"\n  {conclusion}")

total_time = time.time() - t0
print(f"\n  Total time: {total_time:.1f}s")

# ============================================================
# Save Results
# ============================================================
results_json = {
    'experiment_id': 'K479',
    'title': 'Wavelet Decomposition for Volatility Prediction',
    'background': 'K111 showed wavelet < GARCH. K465/K469 showed HAR > GARCH. This tests whether wavelet frequency decomposition improves upon HAR multi-scale aggregation.',
    'references': [
        'Gençay et al. (2002) Physica A — wavelet multi-scaling',
        'In & Kim (2006) JBFA — wavelet hedging',
        'Barunik et al. (2016) JIMF — asymmetric volatility connectedness',
        'Corsi (2009) J Financial Econometrics — HAR-RV model',
        'K111 — wavelet < GARCH (0/9)',
        'K465 — HAR cross-OOS 10/10 with Parkinson proxy',
        'K469 — HAR 8/10 with r² proxy (corrected for tautology)',
    ],
    'method': 'DWT (db4, 4 levels) on |returns|, rolling 252-day window. Energy at each scale as predictors for next-day r². OLS regression, static + rolling (quarterly re-estimation).',
    'asset': 'SPY',
    'data_source': 'yfinance',
    'oos_period': f'{OOS_START} to {OOS_END}',
    'is_window': IS_WINDOW,
    'dwt_wavelet': DWT_WAVELET,
    'dwt_level': DWT_LEVEL,
    'dwt_window': DWT_WINDOW,
    'evaluation_proxy': 'r² (close-to-close squared return)',
    'diagnostics': diagnostics,
    'models': {
        name: {
            'description': info['description'],
        }
        for name, info in models.items()
    },
    'results_static': {
        name: {
            'description': res['description'],
            'qlike': res['qlike'],
            'qlike_log': res['qlike_log'],
            'n_params': res['n_params'],
            'beta': res['beta'],
        }
        for name, res in results_static.items()
    },
    'results_rolling': {
        name: {
            'description': res['description'],
            'qlike': res['qlike'],
            'qlike_log': res['qlike_log'],
            'n_forecasts': res['n_forecasts'],
        }
        for name, res in results_rolling.items()
    },
    'ranking_static': [
        {'rank': i + 1, 'model': name, 'qlike_log': res['qlike_log']}
        for i, (name, res) in enumerate(ranking_static)
    ],
    'ranking_rolling': [
        {'rank': i + 1, 'model': name, 'qlike_log': res['qlike_log']}
        for i, (name, res) in enumerate(ranking_rolling)
    ],
    'dm_tests_static': dm_results_static,
    'dm_tests_rolling': dm_results_rolling,
    'in_sample_r2': {
        'rv21_baseline': r2_baseline,
        'har': r2_har,
        'wavelet_har': r2_wavelet,
        'har_plus_wavelet': r2_combined,
        'low_freq_only': r2_lowfreq,
        'high_freq_only': r2_highfreq,
    },
    'sub_period_analysis': sub_period_results,
    'key_comparison': {
        'static': {
            'har_qlike_log': har_qlike_static,
            'best_wavelet_model': best_wavelet_name_static,
            'best_wavelet_qlike_log': best_wavelet_qlike_static,
            'pct_diff': pct_diff_static,
            'har_wins': har_wins_static,
        },
        'rolling': {
            'har_qlike_log': har_qlike_rolling,
            'best_wavelet_model': best_wavelet_name_rolling,
            'best_wavelet_qlike_log': best_wavelet_qlike_rolling,
            'pct_diff': pct_diff_rolling,
            'har_wins': har_wins_rolling,
        },
    },
    'conclusion': conclusion,
    'relation_to_prior_work': {
        'K111': 'K111 compared wavelet vs GARCH and found GARCH superior. K479 compares wavelet-HAR vs standard HAR — testing if principled frequency decomposition improves upon ad-hoc multi-scale aggregation.',
        'K465_K469': 'HAR (1d/5d/21d) is the current best for next-day vol prediction. K479 tests if replacing or augmenting the HAR scales with wavelet-derived features improves forecast quality.',
    },
    'total_time_seconds': total_time,
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

output_path = 'experiments/k479_wavelet_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
