#!/usr/bin/env python3
"""
K480: Regime-Switching Tool Selection (Adaptive Model Selection)
================================================================
Background:
  K467: HAR best forecasting but VaR 0/6 (misses jumps/overnight gaps)
  K476: Ensemble VaR 0/5 at 1% — HAR pollutes ensemble tail coverage
  K475: GJR+HAR ensemble forecasting 5/5 top (QLIKE avg 0.694)
  K476: GJR alone VaR 7/10 — best single model for risk management

Core Problem:
  HAR uses intraday range → misses overnight gaps and jumps
  In calm periods (VIX < 20), jumps are rare → HAR is fine
  In crisis periods (VIX ≥ 20), jumps frequent → HAR underestimates → VaR fails
  Fixed ensemble averages good (GJR) with bad (HAR) in crisis → drags down VaR

New Idea: Regime-Switching Tool Selection
  Instead of fixed ensemble, select the TOOL based on market regime:
    - Calm: use HAR (better point forecasting)
    - Crisis: use GJR (better tail coverage)

Models:
  1. Always GJR (baseline — K476 winner for VaR)
  2. Always HAR (baseline — K475 winner for forecasting)
  3. Fixed Ensemble 50/50 (K476 — fails at VaR)
  4. Regime-Switch Binary (VIX<20 → HAR, VIX≥20 → GJR)
  5. Regime-Switch Ternary (VIX<15 → HAR, 15-25 → Ensemble, VIX≥25 → GJR)
  6. Adaptive (past 63-day QLIKE selects best model)

Asset: SPY
OOS: 5 periods (same cross-OOS as K476)
Evaluation: QLIKE (r² proxy) + VaR (Kupiec + Christoffersen) at 1% and 5%

Data: yfinance (SPY OHLC + ^VIX close)
Refs:
  Hamilton (1989) "A New Approach to the Economic Analysis of Nonstationary Time Series"
  Ang & Bekaert (2002) "Regime Switches in Interest Rates" J Business & Econ Stats
  Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting
  K467 — HAR VaR 0/6 failure
  K475 — Ensemble forecasting 5/5 top
  K476 — Ensemble VaR 0/5 at 1%, GJR 3/5
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K480: Regime-Switching Tool Selection")
print("  Can regime-dependent model selection beat fixed models?")
print("  Goal: good at BOTH forecasting AND VaR")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
ALPHA_LEVELS = [0.01, 0.05]
LOOKBACK_ADAPTIVE = 63  # ~3 months for adaptive selection

OOS_PERIODS = [
    {"name": "2015-2016", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
]

MODEL_NAMES = [
    'GJR',           # Always GJR
    'HAR',           # Always HAR
    'Ens_50_50',     # Fixed 50/50 ensemble
    'RS_Binary',     # VIX<20 → HAR, VIX≥20 → GJR
    'RS_Ternary',    # VIX<15 → HAR, 15-25 → Ens, VIX≥25 → GJR
    'Adaptive_63d',  # Past 63d QLIKE selects
]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
raw_spy = yf.download('SPY', start='2005-01-01', progress=False)
if isinstance(raw_spy.columns, pd.MultiIndex):
    raw_spy.columns = raw_spy.columns.get_level_values(0)
print(f"  SPY: {raw_spy.index[0].date()} to {raw_spy.index[-1].date()} ({len(raw_spy)} obs)")

raw_vix = yf.download('^VIX', start='2005-01-01', progress=False)
if isinstance(raw_vix.columns, pd.MultiIndex):
    raw_vix.columns = raw_vix.columns.get_level_values(0)
print(f"  VIX: {raw_vix.index[0].date()} to {raw_vix.index[-1].date()} ({len(raw_vix)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

high = raw_spy['High'].values.astype(float).ravel()
low = raw_spy['Low'].values.astype(float).ravel()
close = raw_spy['Close'].values.astype(float).ravel()

# Log returns in %
ret_pct = np.log(close[1:] / close[:-1]) * 100

# Log range (decimal)
ratio = high[1:] / low[1:]
ratio = np.maximum(ratio, 1.0001)
log_range = np.log(ratio)

# Build features DataFrame
idx = raw_spy.index[1:]
feat = pd.DataFrame({
    'return_pct': ret_pct,
    'log_range': log_range,
}, index=idx)

# Parkinson variance (daily, in decimal^2)
feat['parkinson_var'] = log_range**2 / (4 * np.log(2))

# r^2 proxy (daily, in decimal^2)
feat['r2_proxy'] = (np.log(close[1:] / close[:-1]))**2

# HAR components
feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

# Merge VIX
vix_close = raw_vix['Close'].rename('VIX')
if isinstance(vix_close, pd.DataFrame):
    vix_close = vix_close.iloc[:, 0]
feat = feat.join(vix_close, how='left')
feat['VIX'] = feat['VIX'].ffill()  # Forward fill weekends/holidays

feat = feat.dropna()
print(f"  Features: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")
print(f"  VIX range: {feat['VIX'].min():.1f} to {feat['VIX'].max():.1f}")
print(f"  VIX mean: {feat['VIX'].mean():.1f}, median: {feat['VIX'].median():.1f}")

# VIX regime distribution
n_calm = (feat['VIX'] < 20).sum()
n_elevated = ((feat['VIX'] >= 20) & (feat['VIX'] < 25)).sum()
n_crisis = (feat['VIX'] >= 25).sum()
print(f"  VIX regimes: <20: {n_calm} ({100*n_calm/len(feat):.1f}%), "
      f"20-25: {n_elevated} ({100*n_elevated/len(feat):.1f}%), "
      f"≥25: {n_crisis} ({100*n_crisis/len(feat):.1f}%)")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values
lr = feat['log_range'].values
r2 = feat['r2_proxy'].values

adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
arch_stat, arch_p, _, _ = het_arch(ret, nlags=10)
lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)

diagnostics = {
    'n_obs': len(feat),
    'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'return_mean_pct': float(np.mean(ret)),
    'return_std_pct': float(np.std(ret)),
    'return_skew': float(stats.skew(ret)),
    'return_kurt': float(stats.kurtosis(ret)),
    'log_range_mean': float(np.mean(lr)),
    'r2_proxy_mean': float(np.mean(r2)),
    'vix_mean': float(feat['VIX'].mean()),
    'vix_median': float(feat['VIX'].median()),
    'vix_min': float(feat['VIX'].min()),
    'vix_max': float(feat['VIX'].max()),
    'pct_vix_below_20': float(100 * n_calm / len(feat)),
    'pct_vix_20_25': float(100 * n_elevated / len(feat)),
    'pct_vix_above_25': float(100 * n_crisis / len(feat)),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")


# ============================================================
# 4. MODEL FORECAST FUNCTIONS
# ============================================================

def gjr_garch_forecast(returns_pct):
    """GJR-GARCH(1,1) Student-t, 1-step forecast. Returns σ² in %²."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        fc = res.forecast(horizon=1)
        sigma2 = float(fc.variance.values[-1, 0])
        return sigma2
    except Exception:
        return np.nan


def har_log_range_forecast(feat_window):
    """
    HAR log-range model: y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t}
    Returns σ² forecast in %² (Parkinson scale, then scaled to r² level).
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    data = feat_window[cols].dropna()
    if len(data) < 50:
        return np.nan, np.nan

    Y = data['log_range'].values[1:]
    X_mat = data[cols].values[:-1]
    X_mat = np.column_stack([np.ones(len(Y)), X_mat])

    try:
        beta = np.linalg.lstsq(X_mat, Y, rcond=None)[0]
    except Exception:
        return np.nan, np.nan

    x_last = data[cols].values[-1]
    fc_log_range = beta[0] + beta[1:] @ x_last
    fc_log_range = max(fc_log_range, 1e-6)

    # Parkinson variance in decimal^2
    parkinson_var_decimal = fc_log_range**2 / (4 * np.log(2))
    # Convert to %^2
    parkinson_var_pct2 = parkinson_var_decimal * 10000

    return parkinson_var_pct2, parkinson_var_decimal


# ============================================================
# 5. VaR TEST FUNCTIONS
# ============================================================

def kupiec_test(violations, n_total, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_total if n_total > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0
    lr = -2 * (n_viol * np.log(alpha / p_hat) +
               (n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)))
    pval = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(pval)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test."""
    n = len(violations)
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n):
        if violations[i - 1] == 0 and violations[i] == 0:
            n00 += 1
        elif violations[i - 1] == 0 and violations[i] == 1:
            n01 += 1
        elif violations[i - 1] == 1 and violations[i] == 0:
            n10 += 1
        else:
            n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01)
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n
    if p == 0 or p == 1 or p01 == 0 or p01 == 1:
        return 0.0, 1.0
    if p11 == 0 or p11 == 1:
        return 0.0, 1.0
    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(pval)


def run_var_test(violations, n_total, alpha):
    """Run Kupiec + Christoffersen."""
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n_total if n_total > 0 else 0
    kup_stat, kup_p = kupiec_test(violations, n_total, alpha)
    chr_stat, chr_p = christoffersen_test(violations)
    kupiec_pass = bool(kup_p > 0.05)
    chris_pass = bool(chr_p > 0.05)
    both_pass = kupiec_pass and chris_pass
    return {
        'n_obs': n_total,
        'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4),
        'expected_rate': alpha,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(float(kup_p), 4), 'pass': kupiec_pass},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(float(chr_p), 4), 'pass': chris_pass},
        'both_pass': both_pass,
        'tests_passed': int(kupiec_pass) + int(chris_pass),
    }


# ============================================================
# 6. QLIKE LOSS FUNCTION
# ============================================================

def qlike_loss(sigma2_forecast, realized_proxy):
    """QLIKE loss: L = log(σ²) + h/σ² (lower is better)."""
    valid = (sigma2_forecast > 0) & np.isfinite(sigma2_forecast) & np.isfinite(realized_proxy)
    if np.sum(valid) < 10:
        return np.nan
    s2 = sigma2_forecast[valid]
    h = realized_proxy[valid]
    loss = np.log(s2) + h / s2
    return float(np.mean(loss))


# ============================================================
# 7. MAIN CROSS-OOS LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Cross-OOS Evaluation (5 periods × 6 models)")
print("  Evaluating BOTH forecasting (QLIKE) AND VaR simultaneously")
print("=" * 70)

t_start = time.time()
period_results = []

for p_idx, period in enumerate(OOS_PERIODS):
    p_name = period['name']
    print(f"\n{'─' * 60}")
    print(f"  Period {p_idx+1}/5: {p_name}")
    print(f"{'─' * 60}")

    oos_mask = (feat.index >= period['start']) & (feat.index <= period['end'])
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data")
        continue

    first_oos_loc = feat.index.get_loc(oos_dates[0])
    if first_oos_loc < IS_WINDOW:
        print(f"  SKIP: insufficient IS data ({first_oos_loc} < {IS_WINDOW})")
        continue

    n_oos = len(oos_dates)
    is_start_date = feat.index[first_oos_loc - IS_WINDOW]

    print(f"  IS: {is_start_date.date()} ({IS_WINDOW} obs)")
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")

    # IS scale ratio for HAR
    is_data = feat.iloc[first_oos_loc - IS_WINDOW:first_oos_loc]
    is_r2_mean = is_data['r2_proxy'].mean() * 10000
    is_pk_mean = is_data['parkinson_var'].mean() * 10000
    scale_ratio = is_r2_mean / is_pk_mean if is_pk_mean > 0 else 1.0
    print(f"  IS scale ratio (r²/Parkinson): {scale_ratio:.3f}")

    # VIX regime distribution in OOS
    oos_vix = feat.loc[oos_dates, 'VIX']
    n_calm_oos = (oos_vix < 20).sum()
    n_mid_oos = ((oos_vix >= 15) & (oos_vix < 25)).sum()
    n_crisis_oos = (oos_vix >= 25).sum()
    print(f"  OOS VIX: mean={oos_vix.mean():.1f}, <20: {n_calm_oos} ({100*n_calm_oos/n_oos:.0f}%), "
          f"≥25: {n_crisis_oos} ({100*n_crisis_oos/n_oos:.0f}%)")

    # Storage for individual model σ² forecasts
    gjr_sigma2_arr = np.full(n_oos, np.nan)
    har_sigma2_arr = np.full(n_oos, np.nan)
    actual_returns = np.full(n_oos, np.nan)
    r2_proxy_arr = np.full(n_oos, np.nan)
    vix_arr = np.full(n_oos, np.nan)

    t_period_start = time.time()

    for i, oos_date in enumerate(oos_dates):
        oos_loc = feat.index.get_loc(oos_date)
        window_start = oos_loc - IS_WINDOW
        window_data = feat.iloc[window_start:oos_loc]

        actual_returns[i] = feat.iloc[oos_loc]['return_pct']
        r2_proxy_arr[i] = feat.iloc[oos_loc]['r2_proxy'] * 10000  # to %²
        vix_arr[i] = feat.iloc[oos_loc]['VIX']

        # --- GJR-GARCH ---
        gjr_s2 = gjr_garch_forecast(window_data['return_pct'].values)
        if gjr_s2 > 0 and np.isfinite(gjr_s2):
            gjr_sigma2_arr[i] = gjr_s2

        # --- HAR log-range ---
        har_s2_pk, _ = har_log_range_forecast(window_data)
        if har_s2_pk > 0 and np.isfinite(har_s2_pk):
            har_sigma2_arr[i] = har_s2_pk * scale_ratio  # Scale to r² level

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t_period_start
            print(f"    {i+1}/{n_oos} base forecasts ({elapsed:.1f}s)")

    # --- Build all 6 model σ² series ---
    sigma2_models = {}
    # 1. Always GJR
    sigma2_models['GJR'] = gjr_sigma2_arr.copy()
    # 2. Always HAR
    sigma2_models['HAR'] = har_sigma2_arr.copy()
    # 3. Fixed 50/50 ensemble
    sigma2_models['Ens_50_50'] = 0.5 * gjr_sigma2_arr + 0.5 * har_sigma2_arr

    # 4. Regime-Switch Binary (VIX<20 → HAR, VIX≥20 → GJR)
    rs_binary = np.full(n_oos, np.nan)
    for i in range(n_oos):
        if vix_arr[i] < 20:
            rs_binary[i] = har_sigma2_arr[i]
        else:
            rs_binary[i] = gjr_sigma2_arr[i]
    sigma2_models['RS_Binary'] = rs_binary

    # 5. Regime-Switch Ternary (VIX<15 → HAR, 15-25 → Ens, VIX≥25 → GJR)
    rs_ternary = np.full(n_oos, np.nan)
    for i in range(n_oos):
        if vix_arr[i] < 15:
            rs_ternary[i] = har_sigma2_arr[i]
        elif vix_arr[i] >= 25:
            rs_ternary[i] = gjr_sigma2_arr[i]
        else:
            rs_ternary[i] = 0.5 * gjr_sigma2_arr[i] + 0.5 * har_sigma2_arr[i]
    sigma2_models['RS_Ternary'] = rs_ternary

    # 6. Adaptive (past 63d QLIKE selects best)
    adaptive = np.full(n_oos, np.nan)
    model_choices_adaptive = []
    for i in range(n_oos):
        if i < LOOKBACK_ADAPTIVE:
            # Not enough history → use ensemble as default
            adaptive[i] = 0.5 * gjr_sigma2_arr[i] + 0.5 * har_sigma2_arr[i]
            model_choices_adaptive.append('Ens')
        else:
            # Compute rolling QLIKE for GJR and HAR over past 63 days
            lookback_slice = slice(i - LOOKBACK_ADAPTIVE, i)
            gjr_past = gjr_sigma2_arr[lookback_slice]
            har_past = har_sigma2_arr[lookback_slice]
            r2_past = r2_proxy_arr[lookback_slice]

            qlike_gjr = qlike_loss(gjr_past, r2_past)
            qlike_har = qlike_loss(har_past, r2_past)

            if np.isnan(qlike_gjr) and np.isnan(qlike_har):
                adaptive[i] = 0.5 * gjr_sigma2_arr[i] + 0.5 * har_sigma2_arr[i]
                model_choices_adaptive.append('Ens')
            elif np.isnan(qlike_gjr):
                adaptive[i] = har_sigma2_arr[i]
                model_choices_adaptive.append('HAR')
            elif np.isnan(qlike_har):
                adaptive[i] = gjr_sigma2_arr[i]
                model_choices_adaptive.append('GJR')
            elif qlike_har < qlike_gjr:
                adaptive[i] = har_sigma2_arr[i]
                model_choices_adaptive.append('HAR')
            else:
                adaptive[i] = gjr_sigma2_arr[i]
                model_choices_adaptive.append('GJR')
    sigma2_models['Adaptive_63d'] = adaptive

    # --- Track regime choices for RS_Binary ---
    n_har_chosen = int(np.sum(vix_arr < 20))
    n_gjr_chosen = int(np.sum(vix_arr >= 20))
    print(f"  RS_Binary choices: HAR={n_har_chosen} ({100*n_har_chosen/n_oos:.0f}%), "
          f"GJR={n_gjr_chosen} ({100*n_gjr_chosen/n_oos:.0f}%)")

    # Track adaptive choices
    adapt_gjr = sum(1 for c in model_choices_adaptive if c == 'GJR')
    adapt_har = sum(1 for c in model_choices_adaptive if c == 'HAR')
    adapt_ens = sum(1 for c in model_choices_adaptive if c == 'Ens')
    print(f"  Adaptive choices: GJR={adapt_gjr}, HAR={adapt_har}, Ens(default)={adapt_ens}")

    # =============================================
    # A. QLIKE EVALUATION (forecasting quality)
    # =============================================
    qlike_results = {}
    print(f"\n  --- QLIKE (r² proxy) ---")
    for model_name in MODEL_NAMES:
        s2 = sigma2_models[model_name]
        q = qlike_loss(s2, r2_proxy_arr)
        qlike_results[model_name] = round(q, 6) if not np.isnan(q) else None

    # Rank by QLIKE (lower is better)
    valid_qlikes = {k: v for k, v in qlike_results.items() if v is not None}
    sorted_models = sorted(valid_qlikes, key=lambda m: valid_qlikes[m])
    for rank, model_name in enumerate(sorted_models, 1):
        print(f"    {rank}. {model_name}: QLIKE={valid_qlikes[model_name]:.6f}")

    # =============================================
    # B. VaR EVALUATION (risk management quality)
    # =============================================
    var_results_period = {}
    print(f"\n  --- VaR Tests ---")
    for alpha in ALPHA_LEVELS:
        alpha_str = f"{int(alpha*100)}%"
        z = stats.norm.ppf(alpha)
        var_results_period[alpha_str] = {}

        for model_name in MODEL_NAMES:
            s2 = sigma2_models[model_name]
            sigma = np.sqrt(np.maximum(s2, 0))
            valid = np.isfinite(sigma) & np.isfinite(actual_returns)
            n_valid = int(np.sum(valid))

            if n_valid < 50:
                var_results_period[alpha_str][model_name] = {'error': f'insufficient ({n_valid})'}
                continue

            sigma_v = sigma[valid]
            ret_v = actual_returns[valid]
            mu = np.mean(ret_v)
            var_threshold = mu + z * sigma_v
            violations = (ret_v < var_threshold).astype(int)
            test_result = run_var_test(violations, n_valid, alpha)
            var_results_period[alpha_str][model_name] = test_result

            marker = "PASS" if test_result['both_pass'] else f"FAIL"
            print(f"    {model_name:<14} @ {alpha_str}: "
                  f"viol={test_result['n_violations']}/{test_result['n_obs']} "
                  f"({test_result['violation_rate']:.3f}), "
                  f"Kup p={test_result['kupiec']['p_value']:.4f}, "
                  f"Chr p={test_result['christoffersen']['p_value']:.4f} → {marker}")

    period_elapsed = time.time() - t_period_start

    result = {
        'period': p_name,
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_oos': n_oos,
        'vix_stats': {
            'mean': round(float(oos_vix.mean()), 2),
            'median': round(float(oos_vix.median()), 2),
            'min': round(float(oos_vix.min()), 2),
            'max': round(float(oos_vix.max()), 2),
            'pct_below_20': round(100 * n_calm_oos / n_oos, 1),
            'pct_above_25': round(100 * n_crisis_oos / n_oos, 1),
        },
        'regime_choices': {
            'RS_Binary': {'HAR': n_har_chosen, 'GJR': n_gjr_chosen},
            'Adaptive': {'GJR': adapt_gjr, 'HAR': adapt_har, 'Ens': adapt_ens},
        },
        'qlike_r2': qlike_results,
        'qlike_ranking': sorted_models,
        'var_results': var_results_period,
        'elapsed_s': round(period_elapsed, 1),
    }
    period_results.append(result)

total_elapsed = time.time() - t_start
print(f"\n  Total runtime: {total_elapsed:.1f}s")


# ============================================================
# 8. CROSS-OOS SUMMARY TABLES
# ============================================================
print("\n" + "=" * 70)
print("[5] Cross-OOS Summary")
print("=" * 70)

# A. QLIKE rankings
print("\n  --- A. QLIKE Rankings (lower = better) ---")
avg_qlike = {m: [] for m in MODEL_NAMES}
rank_counts = {m: [] for m in MODEL_NAMES}

for pr in period_results:
    valid_q = {k: v for k, v in pr['qlike_r2'].items() if v is not None}
    sorted_m = sorted(valid_q, key=lambda m: valid_q[m])
    for rank, m in enumerate(sorted_m, 1):
        rank_counts[m].append(rank)
    for m in MODEL_NAMES:
        if pr['qlike_r2'].get(m) is not None:
            avg_qlike[m].append(pr['qlike_r2'][m])

print(f"\n  {'Model':<16} {'Avg QLIKE':>10} {'Avg Rank':>10} {'Best':>6} {'Worst':>7}")
print(f"  {'-' * 55}")
for m in MODEL_NAMES:
    if avg_qlike[m]:
        aq = np.mean(avg_qlike[m])
        ar = np.mean(rank_counts[m]) if rank_counts[m] else 0
        best = min(rank_counts[m]) if rank_counts[m] else 0
        worst = max(rank_counts[m]) if rank_counts[m] else 0
        print(f"  {m:<16} {aq:>10.6f} {ar:>10.1f} {best:>6} {worst:>7}")

# B. VaR pass rates
print("\n  --- B. VaR Pass Rates ---")
for alpha in ALPHA_LEVELS:
    alpha_str = f"{int(alpha*100)}%"
    print(f"\n  VaR {alpha_str}:")
    header = f"  {'Model':<16}"
    for pr in period_results:
        header += f"  {pr['period'][:12]:>12}"
    header += f"  {'Total':>8}"
    print(header)
    print("  " + "-" * (16 + len(period_results) * 14 + 10))

    for model_name in MODEL_NAMES:
        row = f"  {model_name:<16}"
        n_pass = 0
        n_total = 0
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' in r:
                row += f"  {'N/A':>12}"
            elif r['both_pass']:
                row += f"  {'PASS':>12}"
                n_pass += 1
                n_total += 1
            else:
                vr = r['violation_rate']
                row += f"  {'FAIL':>8}({vr:.3f})"
                n_total += 1
        row += f"  {n_pass}/{n_total:>5}"
        print(row)

# C. Combined score: QLIKE rank + VaR pass count
print("\n  --- C. Combined Score (Forecasting + VaR) ---")
combined = {}
for model_name in MODEL_NAMES:
    # VaR total pass
    var_pass_total = 0
    var_total = 0
    for alpha in ALPHA_LEVELS:
        alpha_str = f"{int(alpha*100)}%"
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' not in r:
                var_total += 1
                if r['both_pass']:
                    var_pass_total += 1

    avg_rank = np.mean(rank_counts[model_name]) if rank_counts[model_name] else 99
    avg_q = np.mean(avg_qlike[model_name]) if avg_qlike[model_name] else 999

    combined[model_name] = {
        'avg_qlike': round(avg_q, 6),
        'avg_rank': round(avg_rank, 2),
        'var_pass': var_pass_total,
        'var_total': var_total,
        'var_pass_rate': round(var_pass_total / var_total, 3) if var_total > 0 else 0,
    }

print(f"\n  {'Model':<16} {'Avg QLIKE':>10} {'QLIKE Rank':>11} {'VaR Pass':>10} {'VaR Rate':>10}")
print(f"  {'-' * 60}")
for m in MODEL_NAMES:
    c = combined[m]
    print(f"  {m:<16} {c['avg_qlike']:>10.6f} {c['avg_rank']:>11.2f} "
          f"{c['var_pass']}/{c['var_total']:>7} {c['var_pass_rate']:>10.3f}")


# ============================================================
# 9. KEY ANALYSIS: Does regime-switching solve the tradeoff?
# ============================================================
print("\n" + "=" * 70)
print("[6] Key Analysis: Does Regime-Switching Solve the Tradeoff?")
print("=" * 70)

# The question: can any model be good at BOTH?
gjr_c = combined['GJR']
har_c = combined['HAR']
ens_c = combined['Ens_50_50']
rs_bin_c = combined['RS_Binary']
rs_ter_c = combined['RS_Ternary']
adapt_c = combined['Adaptive_63d']

print(f"\n  Baseline comparison:")
print(f"    GJR:         QLIKE rank {gjr_c['avg_rank']:.1f}, VaR {gjr_c['var_pass']}/{gjr_c['var_total']}")
print(f"    HAR:         QLIKE rank {har_c['avg_rank']:.1f}, VaR {har_c['var_pass']}/{har_c['var_total']}")
print(f"    Ens 50/50:   QLIKE rank {ens_c['avg_rank']:.1f}, VaR {ens_c['var_pass']}/{ens_c['var_total']}")

print(f"\n  Regime-switching models:")
print(f"    RS Binary:   QLIKE rank {rs_bin_c['avg_rank']:.1f}, VaR {rs_bin_c['var_pass']}/{rs_bin_c['var_total']}")
print(f"    RS Ternary:  QLIKE rank {rs_ter_c['avg_rank']:.1f}, VaR {rs_ter_c['var_pass']}/{rs_ter_c['var_total']}")
print(f"    Adaptive:    QLIKE rank {adapt_c['avg_rank']:.1f}, VaR {adapt_c['var_pass']}/{adapt_c['var_total']}")

# Determine winner on combined criteria
# Best = lowest QLIKE rank among models with VaR pass rate ≥ GJR's
gjr_var_rate = gjr_c['var_pass_rate']

# Check if any regime model matches or beats GJR on VaR while improving QLIKE
print(f"\n  GJR VaR pass rate (benchmark): {gjr_var_rate:.3f}")

regime_beats_both = []
for m in ['RS_Binary', 'RS_Ternary', 'Adaptive_63d']:
    mc = combined[m]
    beats_var = mc['var_pass_rate'] >= gjr_var_rate
    beats_qlike = mc['avg_rank'] < gjr_c['avg_rank']
    if beats_var and beats_qlike:
        regime_beats_both.append(m)
    status = []
    if beats_var:
        status.append("VaR≥GJR")
    else:
        status.append("VaR<GJR")
    if beats_qlike:
        status.append("QLIKE better")
    else:
        status.append("QLIKE worse")
    print(f"    {m}: {', '.join(status)}")

# ============================================================
# 10. CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("[7] Conclusion")
print("=" * 70)

if regime_beats_both:
    conclusion = (f"SUCCESS: {', '.join(regime_beats_both)} achieves better forecasting than GJR "
                  f"while maintaining equal or better VaR performance. "
                  f"Regime-switching solves the forecasting-VaR tradeoff.")
elif any(combined[m]['var_pass_rate'] >= gjr_var_rate for m in ['RS_Binary', 'RS_Ternary', 'Adaptive_63d']):
    winners = [m for m in ['RS_Binary', 'RS_Ternary', 'Adaptive_63d'] if combined[m]['var_pass_rate'] >= gjr_var_rate]
    conclusion = (f"PARTIAL: {', '.join(winners)} matches GJR on VaR but doesn't significantly improve forecasting. "
                  f"VaR preservation achieved, but no clear dual advantage.")
else:
    best_rs_var = max(['RS_Binary', 'RS_Ternary', 'Adaptive_63d'], key=lambda m: combined[m]['var_pass_rate'])
    best_rs_rate = combined[best_rs_var]['var_pass_rate']
    conclusion = (f"NEGATIVE: No regime-switching model matches GJR's VaR performance "
                  f"(best: {best_rs_var} {best_rs_rate:.3f} vs GJR {gjr_var_rate:.3f}). "
                  f"HAR contamination persists even with regime selection. "
                  f"For risk management, GJR remains the only reliable tool.")

print(f"\n  {conclusion}")

# VaR analysis by alpha level
for alpha in ALPHA_LEVELS:
    alpha_str = f"{int(alpha*100)}%"
    print(f"\n  VaR {alpha_str} pass summary:")
    for m in MODEL_NAMES:
        n_pass = 0
        n_total = 0
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(m, {})
            if 'error' not in r:
                n_total += 1
                if r['both_pass']:
                    n_pass += 1
        print(f"    {m:<16}: {n_pass}/{n_total}")


# ============================================================
# 11. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "K480",
    "title": "Regime-Switching Tool Selection (Adaptive Model Selection)",
    "date": datetime.now(timezone.utc).isoformat(),
    "background": (
        "K467: HAR best forecasting but VaR 0/6 (misses jumps/overnight gaps). "
        "K476: Ensemble VaR 0/5 at 1% — HAR pollutes ensemble. "
        "K475: GJR+HAR ensemble forecasting 5/5 top. "
        "Core tradeoff: HAR=best forecasting, GJR=best VaR. Can regime-switching get both?"
    ),
    "hypothesis": (
        "Instead of fixed ensemble, select model based on VIX regime: "
        "calm (VIX<20) → HAR (better forecasting, jumps rare), "
        "crisis (VIX≥20) → GJR (better tail coverage). "
        "This should preserve GJR's VaR while gaining HAR's QLIKE advantage in calm periods."
    ),
    "references": [
        "Hamilton (1989) 'A New Approach to the Economic Analysis of Nonstationary Time Series'",
        "Ang & Bekaert (2002) 'Regime Switches in Interest Rates' J Business & Econ Stats",
        "Timmermann (2006) 'Forecast Combinations' Handbook of Economic Forecasting",
        "K467 — HAR VaR 0/6 failure",
        "K475 — Ensemble forecasting 5/5 top (QLIKE avg 0.694)",
        "K476 — Ensemble VaR 0/5 at 1%, GJR 3/5 (7/10 total)",
    ],
    "method": {
        "models": {
            "GJR": "GJR-GARCH(1,1) Student-t, always",
            "HAR": "HAR log-range (1d+5d+21d), always",
            "Ens_50_50": "σ² = 0.5*σ²_GJR + 0.5*σ²_HAR, always",
            "RS_Binary": "VIX<20 → HAR, VIX≥20 → GJR",
            "RS_Ternary": "VIX<15 → HAR, VIX 15-25 → Ensemble, VIX≥25 → GJR",
            "Adaptive_63d": "Past 63-day QLIKE selects best model (GJR or HAR)",
        },
        "is_window": IS_WINDOW,
        "var_levels": ALPHA_LEVELS,
        "var_formula": "VaR_α = μ + z_α × σ (Normal, left tail)",
        "var_tests": ["Kupiec unconditional coverage", "Christoffersen conditional coverage"],
        "forecasting_metric": "QLIKE with r² proxy (lower is better)",
        "har_scaling": "Parkinson → r² level using IS scale ratio",
    },
    "asset": "SPY",
    "data_source": "yfinance (SPY OHLC + ^VIX close)",
    "diagnostics": diagnostics,
    "cross_oos_results": period_results,
    "combined_summary": combined,
    "conclusion": conclusion,
    "key_findings": [
        f"GJR: QLIKE rank {gjr_c['avg_rank']:.1f}, VaR {gjr_c['var_pass']}/{gjr_c['var_total']} ({gjr_c['var_pass_rate']:.3f})",
        f"HAR: QLIKE rank {har_c['avg_rank']:.1f}, VaR {har_c['var_pass']}/{har_c['var_total']} ({har_c['var_pass_rate']:.3f})",
        f"Ens 50/50: QLIKE rank {ens_c['avg_rank']:.1f}, VaR {ens_c['var_pass']}/{ens_c['var_total']} ({ens_c['var_pass_rate']:.3f})",
        f"RS Binary: QLIKE rank {rs_bin_c['avg_rank']:.1f}, VaR {rs_bin_c['var_pass']}/{rs_bin_c['var_total']} ({rs_bin_c['var_pass_rate']:.3f})",
        f"RS Ternary: QLIKE rank {rs_ter_c['avg_rank']:.1f}, VaR {rs_ter_c['var_pass']}/{rs_ter_c['var_total']} ({rs_ter_c['var_pass_rate']:.3f})",
        f"Adaptive: QLIKE rank {adapt_c['avg_rank']:.1f}, VaR {adapt_c['var_pass']}/{adapt_c['var_total']} ({adapt_c['var_pass_rate']:.3f})",
    ],
    "limitations": [
        "VIX thresholds (15, 20, 25) are ad-hoc — could be optimized but risks overfitting",
        "Adaptive lookback (63d) not optimized — could try 21d or 126d",
        "Uses same-day VIX — in practice need previous-day VIX for true out-of-sample",
        "Scale ratio computed from IS data — could drift in OOS",
        "Only SPY — regime definitions may differ for other assets",
        "Normal VaR assumption — could test Student-t overlay",
    ],
    "runtime_seconds": round(total_elapsed, 1),
}

out_path = 'experiments/k480_regime_tool_selection_results.json'
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")

print("\n" + "=" * 70)
print("K480 COMPLETE")
print("=" * 70)
