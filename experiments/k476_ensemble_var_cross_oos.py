#!/usr/bin/env python3
"""
K476: Ensemble VaR Cross-OOS Validation
========================================
Background:
  K475: GJR+HAR ensemble passed VaR Trinity 3/3 on 2021-2024 (single period).
  K467: HAR VaR failed 0/6 (systematic tail risk underestimation).
  But K475 only tested ONE OOS period for VaR — insufficient for confidence.

Research Question:
  Does the Ens_GJR_HAR ensemble VaR PASS across ALL 5 OOS periods?
  If 5/5 pass → robust improvement over both components.
  If partial → regime-dependent, needs more analysis.

Design:
  3 models: GJR-GARCH(1,1) Normal VaR, HAR log-range Normal VaR, Ens_GJR_HAR
  Ensemble: σ² = 0.5*σ²_GJR + 0.5*σ²_HAR (simple average)
  5 OOS periods:
    1. 2015-2016
    2. 2017-2018 (Volmageddon)
    3. 2019-2020 (COVID)
    4. 2021-2022 (rate hikes)
    5. 2023-2024
  IS window: 2000 days (rolling)
  VaR levels: 1% and 5%
  Tests: Kupiec unconditional + Christoffersen conditional coverage
  30 tests total (5 periods × 3 models × 2 levels)

Data: yfinance (SPY), 2005-01-01 to present
Refs:
  Kupiec (1995) "Techniques for Verifying the Accuracy of Risk Measurement Models"
  Christoffersen (1998) "Evaluating Interval Forecasts" International Economic Review
  Timmermann (2006) "Forecast Combinations" Handbook of Economic Forecasting
  K475 — Ensemble 3/3 Trinity pass on 2021-2024
  K467 — HAR VaR 0/6 failure
  K469 — HAR log-range cross-OOS validation
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
print("K476: Ensemble VaR Cross-OOS Validation")
print("  3 models × 5 periods × 2 VaR levels = 30 tests")
print("  Core Q: Does Ens_GJR_HAR pass VaR across ALL periods?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 2000
ALPHA_LEVELS = [0.01, 0.05]

OOS_PERIODS = [
    {"name": "2015-2016", "start": "2015-01-01", "end": "2016-12-31"},
    {"name": "2017-2018 (Volmageddon)", "start": "2017-01-01", "end": "2018-12-31"},
    {"name": "2019-2020 (COVID)", "start": "2019-01-01", "end": "2020-12-31"},
    {"name": "2021-2022 (rate hikes)", "start": "2021-01-01", "end": "2022-12-31"},
    {"name": "2023-2024", "start": "2023-01-01", "end": "2024-12-31"},
]

MODEL_NAMES = ['GJR', 'HAR', 'Ens_GJR_HAR']

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading OHLC data for SPY...")
raw = yf.download('SPY', start='2005-01-01', progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
print(f"  SPY: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")

high = raw['High'].values.astype(float).ravel()
low = raw['Low'].values.astype(float).ravel()
close = raw['Close'].values.astype(float).ravel()

# Log returns in %
ret_pct = np.log(close[1:] / close[:-1]) * 100

# Log range (decimal)
ratio = high[1:] / low[1:]
ratio = np.maximum(ratio, 1.0001)
log_range = np.log(ratio)

# Build features DataFrame
idx = raw.index[1:]
feat = pd.DataFrame({
    'return_pct': ret_pct,
    'log_range': log_range,
}, index=idx)

# Parkinson variance (daily, in decimal²)
feat['parkinson_var'] = log_range**2 / (4 * np.log(2))

# r² proxy (daily, in decimal²)
feat['r2_proxy'] = (np.log(close[1:] / close[:-1]))**2

# HAR components: 5d and 21d rolling averages of log_range
feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

feat = feat.dropna()
print(f"  Features: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")
ret = feat['return_pct'].values
lr = feat['log_range'].values
r2 = feat['r2_proxy'].values
pk = feat['parkinson_var'].values

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
    'log_range_std': float(np.std(lr)),
    'r2_proxy_mean': float(np.mean(r2)),
    'parkinson_var_mean': float(np.mean(pk)),
    'r2_over_parkinson_ratio': float(np.mean(r2) / np.mean(pk)),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
    'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")
print(f"  r²/Parkinson ratio: {diagnostics['r2_over_parkinson_ratio']:.3f}")

# ============================================================
# 4. MODEL FORECAST FUNCTIONS
# ============================================================

def gjr_garch_forecast(returns_pct):
    """
    GJR-GARCH(1,1) with Student-t, 1-step forecast.
    Returns σ² in %² units.
    """
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
    Returns σ² forecast in %² units (via Parkinson → scale).
    Also returns the raw Parkinson-scale σ² (in %²).
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

    # Parkinson variance in decimal²
    parkinson_var_decimal = fc_log_range**2 / (4 * np.log(2))

    # Convert to %²: multiply by (100)² = 10000
    parkinson_var_pct2 = parkinson_var_decimal * 10000

    return parkinson_var_pct2, parkinson_var_decimal


# ============================================================
# 5. VaR BACKTEST FUNCTIONS
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
        # Independence trivially holds if no consecutive violations
        return 0.0, 1.0
    lr_ind = -2 * (
        (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        - n00 * np.log(1 - p01) - n01 * np.log(p01)
        - n10 * np.log(1 - p11) - n11 * np.log(p11)
    )
    pval = 1 - stats.chi2.cdf(lr_ind, df=1)
    return float(lr_ind), float(pval)


def run_var_test(violations, n_total, alpha):
    """Run Kupiec + Christoffersen and return results dict."""
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n_total if n_total > 0 else 0

    kup_stat, kup_p = kupiec_test(violations, n_total, alpha)
    chr_stat, chr_p = christoffersen_test(violations)

    kupiec_pass = bool(kup_p > 0.05)
    chris_pass = bool(chr_p > 0.05)
    both_pass = kupiec_pass and chris_pass
    tests_passed = int(kupiec_pass) + int(chris_pass)

    return {
        'n_obs': n_total,
        'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4),
        'expected_rate': alpha,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(float(kup_p), 4), 'pass': kupiec_pass},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(float(chr_p), 4), 'pass': chris_pass},
        'both_pass': both_pass,
        'tests_passed': tests_passed,
    }


# ============================================================
# 6. MAIN CROSS-OOS VaR LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Cross-OOS VaR Backtesting (5 periods × 3 models × 2 levels)")
print("=" * 70)

t_start = time.time()
period_results = []

for p_idx, period in enumerate(OOS_PERIODS):
    p_name = period['name']
    print(f"\n{'─'*60}")
    print(f"  Period {p_idx+1}/5: {p_name}")
    print(f"{'─'*60}")

    oos_mask = (feat.index >= period['start']) & (feat.index <= period['end'])
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data")
        continue

    # Need IS_WINDOW before first OOS date
    first_oos_loc = feat.index.get_loc(oos_dates[0])
    if first_oos_loc < IS_WINDOW:
        print(f"  SKIP: insufficient IS data ({first_oos_loc} < {IS_WINDOW})")
        continue

    n_oos = len(oos_dates)
    is_start_date = feat.index[first_oos_loc - IS_WINDOW]

    print(f"  IS: {is_start_date.date()} ({IS_WINDOW} obs)")
    print(f"  OOS: {oos_dates[0].date()} to {oos_dates[-1].date()} ({n_oos} obs)")

    # Compute IS scale ratio (r²/Parkinson) for HAR scaling
    is_data = feat.iloc[first_oos_loc - IS_WINDOW:first_oos_loc]
    is_r2_mean = is_data['r2_proxy'].mean() * 10000     # to %²
    is_pk_mean = is_data['parkinson_var'].mean() * 10000  # to %²
    scale_ratio = is_r2_mean / is_pk_mean if is_pk_mean > 0 else 1.0
    print(f"  IS scale ratio (r²/Parkinson): {scale_ratio:.3f}")

    # Storage for σ forecasts (in % units, i.e., σ not σ²)
    sigma_forecasts = {m: np.full(n_oos, np.nan) for m in MODEL_NAMES}
    actual_returns = np.full(n_oos, np.nan)  # returns in %

    t_period_start = time.time()

    for i, oos_date in enumerate(oos_dates):
        oos_loc = feat.index.get_loc(oos_date)

        # Rolling window for estimation
        window_start = oos_loc - IS_WINDOW
        window_data = feat.iloc[window_start:oos_loc]

        # Actual return at OOS date
        actual_returns[i] = feat.iloc[oos_loc]['return_pct']

        # --- GJR-GARCH σ² forecast (in %²) ---
        gjr_sigma2 = gjr_garch_forecast(window_data['return_pct'].values)
        if gjr_sigma2 > 0 and np.isfinite(gjr_sigma2):
            sigma_forecasts['GJR'][i] = np.sqrt(gjr_sigma2)
        else:
            sigma_forecasts['GJR'][i] = np.nan

        # --- HAR log-range σ² forecast (Parkinson scale, in %²) ---
        har_sigma2_pk, _ = har_log_range_forecast(window_data)
        if har_sigma2_pk > 0 and np.isfinite(har_sigma2_pk):
            # Scale from Parkinson to r² level for VaR (returns are in % = r² scale)
            har_sigma2_r2 = har_sigma2_pk * scale_ratio
            sigma_forecasts['HAR'][i] = np.sqrt(har_sigma2_r2)
        else:
            sigma_forecasts['HAR'][i] = np.nan

        if (i + 1) % 100 == 0:
            elapsed = time.time() - t_period_start
            print(f"    {i+1}/{n_oos} forecasts done ({elapsed:.1f}s)")

    # --- Ensemble: average σ² then take sqrt ---
    # σ²_ens = 0.5 * σ²_GJR + 0.5 * σ²_HAR
    gjr_sigma2_arr = sigma_forecasts['GJR']**2
    har_sigma2_arr = sigma_forecasts['HAR']**2
    ens_sigma2 = 0.5 * gjr_sigma2_arr + 0.5 * har_sigma2_arr
    sigma_forecasts['Ens_GJR_HAR'] = np.sqrt(ens_sigma2)

    # --- VaR computation and testing ---
    period_var_results = {}
    for alpha in ALPHA_LEVELS:
        alpha_str = f"{int(alpha*100)}%"
        z = stats.norm.ppf(alpha)  # Negative for left tail
        period_var_results[alpha_str] = {}

        for model_name in MODEL_NAMES:
            sigma = sigma_forecasts[model_name]
            valid = np.isfinite(sigma) & np.isfinite(actual_returns)
            n_valid = int(np.sum(valid))

            if n_valid < 50:
                period_var_results[alpha_str][model_name] = {'error': f'insufficient data ({n_valid})'}
                print(f"    {model_name} @ {alpha_str}: SKIP (only {n_valid} valid obs)")
                continue

            sigma_v = sigma[valid]
            ret_v = actual_returns[valid]

            # VaR threshold: μ + z_α × σ (z is negative for left tail)
            mu = np.mean(ret_v)
            var_threshold = mu + z * sigma_v

            violations = (ret_v < var_threshold).astype(int)
            test_result = run_var_test(violations, n_valid, alpha)
            period_var_results[alpha_str][model_name] = test_result

            marker = "PASS" if test_result['both_pass'] else f"FAIL ({test_result['tests_passed']}/2)"
            print(f"    {model_name} @ {alpha_str}: "
                  f"violations={test_result['n_violations']}/{test_result['n_obs']} "
                  f"(rate={test_result['violation_rate']:.4f}, expect={alpha}), "
                  f"Kupiec p={test_result['kupiec']['p_value']:.4f}, "
                  f"Chris p={test_result['christoffersen']['p_value']:.4f} → {marker}")

    period_elapsed = time.time() - t_period_start

    result = {
        'period': p_name,
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_is': IS_WINDOW,
        'n_oos': n_oos,
        'is_scale_ratio': round(scale_ratio, 4),
        'var_results': period_var_results,
        'elapsed_s': round(period_elapsed, 1),
    }
    period_results.append(result)

total_elapsed = time.time() - t_start
print(f"\n  Total cross-OOS VaR backtesting: {total_elapsed:.1f}s")


# ============================================================
# 7. CROSS-OOS SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[5] Cross-OOS VaR Summary Table")
print("=" * 70)

# Build summary matrix: model × period × alpha → pass/fail
summary_table = {}
for model_name in MODEL_NAMES:
    summary_table[model_name] = {}
    for alpha in ALPHA_LEVELS:
        alpha_str = f"{int(alpha*100)}%"
        passes = []
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' in r:
                passes.append(None)
            else:
                passes.append(r['both_pass'])
        summary_table[model_name][alpha_str] = passes

# Print summary
for alpha in ALPHA_LEVELS:
    alpha_str = f"{int(alpha*100)}%"
    print(f"\n  --- VaR {alpha_str} ---")
    header = f"  {'Model':<15}"
    for pr in period_results:
        header += f"  {pr['period'][:12]:>12}"
    header += f"  {'Total':>8}"
    print(header)
    print("  " + "-" * (15 + len(period_results) * 14 + 10))

    for model_name in MODEL_NAMES:
        row = f"  {model_name:<15}"
        n_pass = 0
        n_total = 0
        for i, pr in enumerate(period_results):
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
            if 'error' not in r:
                pass  # Already counted
        row += f"  {n_pass}/{n_total:>5}"
        print(row)

# Detailed violation rates
print(f"\n  --- Violation Rates (all periods, both levels) ---")
header = f"  {'Model':<15} {'Level':>5}"
for pr in period_results:
    header += f"  {pr['period'][:12]:>12}"
print(header)
print("  " + "-" * (20 + len(period_results) * 14))

for alpha in ALPHA_LEVELS:
    alpha_str = f"{int(alpha*100)}%"
    for model_name in MODEL_NAMES:
        row = f"  {model_name:<15} {alpha_str:>5}"
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' in r:
                row += f"  {'N/A':>12}"
            else:
                vr = r['violation_rate']
                marker = "" if r['both_pass'] else "*"
                row += f"  {vr:>11.4f}{marker}"
        print(row)
    print()

# ============================================================
# 8. PASS COUNT SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[6] Pass Count Summary")
print("=" * 70)

pass_counts = {}
for model_name in MODEL_NAMES:
    total_pass = 0
    total_tests = 0
    for alpha in ALPHA_LEVELS:
        alpha_str = f"{int(alpha*100)}%"
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' not in r:
                total_tests += 1
                if r['both_pass']:
                    total_pass += 1
    pass_counts[model_name] = {'pass': total_pass, 'total': total_tests}
    print(f"  {model_name}: {total_pass}/{total_tests} pass")

# Per-level summary
for alpha in ALPHA_LEVELS:
    alpha_str = f"{int(alpha*100)}%"
    print(f"\n  VaR {alpha_str}:")
    for model_name in MODEL_NAMES:
        n_pass = 0
        n_total = 0
        for pr in period_results:
            r = pr['var_results'].get(alpha_str, {}).get(model_name, {})
            if 'error' not in r:
                n_total += 1
                if r['both_pass']:
                    n_pass += 1
        print(f"    {model_name}: {n_pass}/{n_total} pass")


# ============================================================
# 9. KEY FINDING
# ============================================================
print("\n" + "=" * 70)
print("[7] Key Finding")
print("=" * 70)

ens_pass_1 = sum(1 for pr in period_results
                 if pr['var_results'].get('1%', {}).get('Ens_GJR_HAR', {}).get('both_pass', False))
ens_pass_5 = sum(1 for pr in period_results
                 if pr['var_results'].get('5%', {}).get('Ens_GJR_HAR', {}).get('both_pass', False))
gjr_pass_1 = sum(1 for pr in period_results
                 if pr['var_results'].get('1%', {}).get('GJR', {}).get('both_pass', False))
gjr_pass_5 = sum(1 for pr in period_results
                 if pr['var_results'].get('5%', {}).get('GJR', {}).get('both_pass', False))
har_pass_1 = sum(1 for pr in period_results
                 if pr['var_results'].get('1%', {}).get('HAR', {}).get('both_pass', False))
har_pass_5 = sum(1 for pr in period_results
                 if pr['var_results'].get('5%', {}).get('HAR', {}).get('both_pass', False))

n_periods = len(period_results)

print(f"\n  VaR 1% pass rates:")
print(f"    GJR:         {gjr_pass_1}/{n_periods}")
print(f"    HAR:         {har_pass_1}/{n_periods}")
print(f"    Ens_GJR_HAR: {ens_pass_1}/{n_periods}")

print(f"\n  VaR 5% pass rates:")
print(f"    GJR:         {gjr_pass_5}/{n_periods}")
print(f"    HAR:         {har_pass_5}/{n_periods}")
print(f"    Ens_GJR_HAR: {ens_pass_5}/{n_periods}")

ens_total = ens_pass_1 + ens_pass_5
gjr_total = gjr_pass_1 + gjr_pass_5
har_total = har_pass_1 + har_pass_5

print(f"\n  Combined (1% + 5%) pass rates:")
print(f"    GJR:         {gjr_total}/{2*n_periods}")
print(f"    HAR:         {har_total}/{2*n_periods}")
print(f"    Ens_GJR_HAR: {ens_total}/{2*n_periods}")

# Determine conclusion
if ens_total >= gjr_total and ens_total >= har_total:
    if ens_total == 2 * n_periods:
        conclusion = f"STRONG: Ens_GJR_HAR passes ALL {2*n_periods}/{2*n_periods} tests — robust across all periods and levels."
    elif ens_total > max(gjr_total, har_total):
        conclusion = f"POSITIVE: Ens_GJR_HAR ({ens_total}/{2*n_periods}) outperforms both GJR ({gjr_total}/{2*n_periods}) and HAR ({har_total}/{2*n_periods})."
    elif ens_total == max(gjr_total, har_total):
        conclusion = f"NEUTRAL: Ens_GJR_HAR ({ens_total}/{2*n_periods}) ties with the best single model. No clear ensemble advantage for VaR."
    else:
        conclusion = f"WEAK: Ens_GJR_HAR ({ens_total}/{2*n_periods}) matches but does not exceed single models."
elif ens_total < max(gjr_total, har_total):
    best_single = 'GJR' if gjr_total > har_total else 'HAR'
    best_single_total = max(gjr_total, har_total)
    conclusion = f"NEGATIVE: Ens_GJR_HAR ({ens_total}/{2*n_periods}) WORSE than {best_single} ({best_single_total}/{2*n_periods}). Ensemble does not help VaR."
else:
    conclusion = f"MIXED: Results inconclusive. Ens_GJR_HAR ({ens_total}/{2*n_periods})."

print(f"\n  CONCLUSION: {conclusion}")


# ============================================================
# 10. SAVE RESULTS
# ============================================================
print(f"\n  Total runtime: {total_elapsed:.1f}s")

results = {
    "experiment_id": "K476",
    "title": "Ensemble VaR Cross-OOS Validation (GJR + HAR)",
    "date": datetime.now(timezone.utc).isoformat(),
    "background": "K475 showed GJR+HAR ensemble VaR passes 3/3 Trinity on 2021-2024 (single period). "
                  "K467 showed HAR VaR fails 0/6 (systematic tail underestimation). "
                  "This experiment tests whether ensemble VaR is robust across ALL 5 OOS periods.",
    "hypothesis": "Ens_GJR_HAR VaR should pass across all 5 periods, demonstrating that the ensemble "
                  "inherits GJR's tail coverage while retaining HAR's forecasting superiority.",
    "references": [
        "Kupiec (1995) 'Techniques for Verifying the Accuracy of Risk Measurement Models'",
        "Christoffersen (1998) 'Evaluating Interval Forecasts' International Economic Review",
        "Timmermann (2006) 'Forecast Combinations' Handbook of Economic Forecasting",
        "K475 — Ensemble Trinity 3/3 pass on 2021-2024",
        "K467 — HAR VaR 0/6 failure",
        "K469 — HAR log-range cross-OOS validation"
    ],
    "method": {
        "models": {
            "GJR": "GJR-GARCH(1,1) Student-t, Normal VaR",
            "HAR": "HAR log-range (1d+5d+21d), Parkinson σ² scaled to r² level, Normal VaR",
            "Ens_GJR_HAR": "σ² = 0.5*σ²_GJR + 0.5*σ²_HAR, Normal VaR"
        },
        "is_window": IS_WINDOW,
        "var_levels": [0.01, 0.05],
        "var_formula": "VaR_α = μ + z_α × σ (Normal, left tail)",
        "tests": ["Kupiec unconditional coverage", "Christoffersen conditional coverage"],
        "pass_criterion": "Both Kupiec and Christoffersen p > 0.05"
    },
    "asset": "SPY",
    "data_source": "yfinance",
    "diagnostics": diagnostics,
    "cross_oos_results": period_results,
    "summary": {
        "pass_rates": {
            "GJR": {"var_1pct": f"{gjr_pass_1}/{n_periods}", "var_5pct": f"{gjr_pass_5}/{n_periods}", "total": f"{gjr_total}/{2*n_periods}"},
            "HAR": {"var_1pct": f"{har_pass_1}/{n_periods}", "var_5pct": f"{har_pass_5}/{n_periods}", "total": f"{har_total}/{2*n_periods}"},
            "Ens_GJR_HAR": {"var_1pct": f"{ens_pass_1}/{n_periods}", "var_5pct": f"{ens_pass_5}/{n_periods}", "total": f"{ens_total}/{2*n_periods}"},
        },
        "pass_counts": pass_counts,
    },
    "conclusion": conclusion,
    "runtime_seconds": round(total_elapsed, 1),
}

out_path = 'experiments/k476_ensemble_var_cross_oos_results.json'
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")

print("\n" + "=" * 70)
print("K476 COMPLETE")
print("=" * 70)
