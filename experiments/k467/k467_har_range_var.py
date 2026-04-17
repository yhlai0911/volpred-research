#!/usr/bin/env python3
"""
K467: HAR Log-Range Based VaR Estimation
=========================================
Background:
  K465: HAR log-range 10/10 cross-OOS (publication ready) — best vol forecaster
  K454: Semivariance (RS⁻) VaR passes Trinity 3/3 at 1% (beats GARCH Skewed-t 1/3)

  If HAR log-range is a better σ forecaster, does it produce better VaR?

VaR Methods (6 total):
  1. GJR-GARCH Normal VaR (baseline)
     σ from GJR-GARCH → VaR = μ - z_α · σ
  2. GJR-GARCH Skewed-t VaR
     σ from GJR-GARCH → quantile from skewed-t distribution
  3. RS⁻ Normal VaR (K454 winner)
     σ from semivariance EWMA → VaR = μ - z_α · σ
  4. HAR log-range VaR (NEW)
     σ from HAR log-range forecast → Parkinson → VaR = μ - z_α · σ
  5. HAR + Semi combined VaR
     σ = 0.5 · σ_HAR + 0.5 · σ_RS⁻ → VaR = μ - z_α · σ
  6. Hybrid GARCH + HAR
     σ = 0.5 · σ_GARCH + 0.5 · σ_HAR → VaR = μ - z_α · σ

Assets: SPY, QQQ, EEM (same as K454)
OOS: 2023-2024 (~502 days)
Rolling window: 504 trading days

Trinity Test at 1% and 5%:
  - Kupiec (1995) unconditional coverage
  - Christoffersen (1998) independence
  - Engle & Manganelli (2004) Dynamic Quantile (DQ)

Data source: yfinance (OHLC data for range-based measures, Close for returns)
Refs: Corsi (2009) JFE, Patton & Sheppard (2015), Kupiec (1995),
      Alizadeh Brandt Diebold (2002) JFE, K454, K465
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import sys
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from arch.univariate.distribution import SkewStudent
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K467: HAR Log-Range Based VaR Estimation")
print("  Does the best vol forecaster (HAR log-range) also produce the best VaR?")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'QQQ', 'EEM']
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
ROLLING_WINDOW = 504  # ~2 years
HAR_MIN_WINDOW = 252  # minimum for HAR (need 21d rolling averages + estimation)
ALPHA_LEVELS = [0.01, 0.05]
METHODS = [
    'GJR-Normal',
    'GJR-SkewT',
    'RS_neg-Normal',
    'HAR-Range-Normal',
    'HAR+Semi-Combined',
    'Hybrid-GARCH+HAR',
]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading OHLC data...")
raw_data = {}
for ticker in ASSETS:
    raw = yf.download(ticker, start='2005-01-01', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw_data[ticker] = raw
    print(f"  {ticker}: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")


# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features...")


def compute_features(df):
    """Compute returns, log-range, HAR components, Parkinson vol."""
    high = df['High'].values.astype(float).ravel()
    low = df['Low'].values.astype(float).ravel()
    close = df['Close'].values.astype(float).ravel()

    # Log returns in %
    ret = np.log(close[1:] / close[:-1]) * 100

    # Log range
    ratio = high[1:] / low[1:]
    ratio = np.maximum(ratio, 1.0001)
    log_range = np.log(ratio)

    # Build DataFrame
    idx = df.index[1:]
    feat = pd.DataFrame({
        'return': ret,
        'log_range': log_range,
    }, index=idx)

    # HAR components: 5d and 21d averages of log_range
    feat['log_range_5d'] = feat['log_range'].rolling(5).mean()
    feat['log_range_21d'] = feat['log_range'].rolling(21).mean()

    feat = feat.dropna()
    return feat


features = {}
for ticker in ASSETS:
    features[ticker] = compute_features(raw_data[ticker])
    print(f"  {ticker}: {len(features[ticker])} obs with all features")


# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3] Data diagnostics...")

diagnostics_all = {}
for ticker in ASSETS:
    feat = features[ticker]
    ret = feat['return'].values
    lr = feat['log_range'].values

    diag = {
        'n_obs': len(feat),
        'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
        'return_mean': float(np.mean(ret)),
        'return_std': float(np.std(ret)),
        'return_skew': float(stats.skew(ret)),
        'return_kurt': float(stats.kurtosis(ret)),
        'log_range_mean': float(np.mean(lr)),
        'log_range_std': float(np.std(lr)),
    }

    # ADF on returns
    adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
    diag['adf_stat'] = float(adf_stat)
    diag['adf_p'] = float(adf_p)
    diag['is_stationary'] = bool(adf_p < 0.05)

    # ARCH-LM on returns
    arch_stat, arch_p, _, _ = het_arch(ret, nlags=10)
    diag['arch_lm_stat'] = float(arch_stat)
    diag['arch_lm_p'] = float(arch_p)
    diag['has_arch_effects'] = bool(arch_p < 0.05)

    # Ljung-Box on squared returns
    lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)
    diag['ljung_box_sq_p10'] = float(lb['lb_pvalue'].values[0])

    diagnostics_all[ticker] = diag
    print(f"  {ticker}: n={diag['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'}), "
          f"ARCH-LM p={arch_p:.2e} ({'YES' if arch_p < 0.05 else 'NO'})")


# ============================================================
# 4. TRINITY TEST FUNCTIONS
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
    """Christoffersen (1998) independence test."""
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


def dq_test(violations, var_forecasts, actual_returns, n_lags=4):
    """Engle & Manganelli (2004) Dynamic Quantile test."""
    T = len(violations)
    if T <= n_lags + 2:
        return 0.0, 1.0

    hits = violations.astype(float) - np.mean(violations)

    X = np.ones((T - n_lags, 1))
    for lag in range(1, n_lags + 1):
        X = np.column_stack([X, hits[n_lags - lag:T - lag]])
    X = np.column_stack([X, var_forecasts[n_lags:]])

    y = hits[n_lags:]

    try:
        XtX = X.T @ X
        XtX_inv = np.linalg.inv(XtX + 1e-10 * np.eye(XtX.shape[0]))
        beta = XtX_inv @ X.T @ y
        dq_stat = float(beta.T @ X.T @ X @ beta)
        pval = 1 - stats.chi2.cdf(dq_stat, df=X.shape[1])
        return float(dq_stat), float(pval)
    except np.linalg.LinAlgError:
        return 0.0, 1.0


def run_trinity(violations, var_fcasts, actuals, alpha):
    """Run all three tests and return results dict."""
    n = len(violations)
    n_viol = int(np.sum(violations))
    viol_rate = n_viol / n if n > 0 else 0

    kup_stat, kup_p = kupiec_test(violations, n, alpha)
    chr_stat, chr_p = christoffersen_test(violations)
    dq_stat, dq_p = dq_test(violations, var_fcasts, actuals)

    trinity_pass = bool(kup_p > 0.05 and chr_p > 0.05 and dq_p > 0.05)
    tests_passed = sum([kup_p > 0.05, chr_p > 0.05, dq_p > 0.05])

    return {
        'n_obs': n,
        'n_violations': n_viol,
        'violation_rate': round(viol_rate, 4),
        'expected_rate': alpha,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(float(kup_p), 4)},
        'christoffersen': {'stat': round(chr_stat, 4), 'p_value': round(float(chr_p), 4)},
        'dq': {'stat': round(dq_stat, 4), 'p_value': round(float(dq_p), 4)},
        'trinity_pass': trinity_pass,
        'tests_passed': tests_passed,
    }


# ============================================================
# 5. HAR LOG-RANGE VOLATILITY FORECASTER
# ============================================================

def har_log_range_vol(feat_window):
    """
    Estimate HAR log-range model on window, forecast 1-step ahead σ.
    y_{t+1} = b0 + b1*y_t + b2*y_{5d,t} + b3*y_{21d,t} + e

    Returns forecast σ in percentage units (comparable to GARCH σ).
    """
    cols = ['log_range', 'log_range_5d', 'log_range_21d']
    data = feat_window[cols].dropna()

    if len(data) < 50:
        return np.nan

    Y = data['log_range'].values[1:]  # y_{t+1}
    X = data[cols].values[:-1]
    X = np.column_stack([np.ones(len(Y)), X])

    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return np.nan

    # Forecast using most recent values
    x_last = data[cols].values[-1]
    fc_log_range = beta[0] + beta[1:] @ x_last

    # Ensure positive
    fc_log_range = max(fc_log_range, 1e-6)

    # Convert: Parkinson variance = log_range^2 / (4*ln2)
    parkinson_var = fc_log_range**2 / (4 * np.log(2))

    # Parkinson var is in decimal^2 (log-return)
    # Convert to % units: sqrt(var) * 100
    sigma_pct = np.sqrt(parkinson_var) * 100

    return sigma_pct


# ============================================================
# 6. MAIN VaR BACKTESTING LOOP
# ============================================================
print("\n" + "=" * 70)
print("[4] Rolling VaR Backtesting (3 assets × 6 methods × 2 levels)")
print("=" * 70)

skewt_dist = SkewStudent()
t_start = time.time()

all_results = {}

for ticker in ASSETS:
    print(f"\n{'='*60}")
    print(f"  ASSET: {ticker}")
    print(f"{'='*60}")

    feat = features[ticker]
    returns_series = feat['return']
    returns_arr = returns_series.values
    returns_idx = returns_series.index
    n_total = len(returns_arr)

    # Find OOS range
    oos_mask = (returns_idx >= OOS_START) & (returns_idx <= OOS_END)
    oos_dates = returns_idx[oos_mask]

    if len(oos_dates) == 0:
        print(f"  SKIP: no OOS data in {OOS_START} to {OOS_END}")
        continue

    # Find array indices for OOS
    oos_start_idx = None
    for i in range(n_total):
        if returns_idx[i] >= pd.Timestamp(OOS_START):
            oos_start_idx = i
            break

    oos_end_idx = None
    for i in range(n_total):
        if returns_idx[i] > pd.Timestamp(OOS_END):
            oos_end_idx = i
            break
    if oos_end_idx is None:
        oos_end_idx = n_total

    n_oos = oos_end_idx - oos_start_idx

    if oos_start_idx < ROLLING_WINDOW:
        print(f"  ERROR: not enough IS data ({oos_start_idx} < {ROLLING_WINDOW})")
        continue

    print(f"  OOS: {returns_idx[oos_start_idx].date()} to {returns_idx[oos_end_idx-1].date()} ({n_oos} days)")
    print(f"  Rolling window: {ROLLING_WINDOW} days")

    # Storage: method -> alpha -> list of (var_forecast, actual_return)
    var_store = {m: {a: {'var': [], 'actual': []} for a in ALPHA_LEVELS} for m in METHODS}

    progress_marks = set([int(n_oos * p) for p in [0.25, 0.5, 0.75, 1.0]])

    for t_idx in range(oos_start_idx, oos_end_idx):
        progress = t_idx - oos_start_idx
        if progress in progress_marks:
            pct = progress / n_oos * 100
            print(f"    Progress: {pct:.0f}% ({progress}/{n_oos})")

        is_start = t_idx - ROLLING_WINDOW
        is_returns = returns_arr[is_start:t_idx]
        actual_return = returns_arr[t_idx]

        # ---- Method 1: GJR-GARCH Normal VaR ----
        gjr_cond_vol = np.nan
        gjr_cond_mean = np.nan
        try:
            model = arch_model(is_returns, vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = model.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            gjr_cond_var = fc.variance.values[-1, 0]
            gjr_cond_vol = np.sqrt(gjr_cond_var)
            gjr_cond_mean = fc.mean.values[-1, 0]
            for alpha in ALPHA_LEVELS:
                z = stats.norm.ppf(alpha)
                var_f = gjr_cond_mean + z * gjr_cond_vol
                var_store['GJR-Normal'][alpha]['var'].append(var_f)
                var_store['GJR-Normal'][alpha]['actual'].append(actual_return)
        except Exception:
            for alpha in ALPHA_LEVELS:
                var_store['GJR-Normal'][alpha]['var'].append(np.nan)
                var_store['GJR-Normal'][alpha]['actual'].append(actual_return)

        # ---- Method 2: GJR-GARCH Skewed-t VaR ----
        try:
            model_st = arch_model(is_returns, vol='GARCH', p=1, o=1, q=1, dist='skewt')
            res_st = model_st.fit(disp='off', show_warning=False)
            fc_st = res_st.forecast(horizon=1)
            cond_var_st = fc_st.variance.values[-1, 0]
            cond_vol_st = np.sqrt(cond_var_st)
            cond_mean_st = fc_st.mean.values[-1, 0]

            eta = res_st.params.get('eta', res_st.params.get('nu', 8.0))
            lam = res_st.params.get('lambda', 0.0)

            for alpha in ALPHA_LEVELS:
                z_st = skewt_dist.ppf(alpha, parameters=np.array([eta, lam]))
                var_f = cond_mean_st + z_st * cond_vol_st
                var_store['GJR-SkewT'][alpha]['var'].append(var_f)
                var_store['GJR-SkewT'][alpha]['actual'].append(actual_return)
        except Exception:
            for alpha in ALPHA_LEVELS:
                var_store['GJR-SkewT'][alpha]['var'].append(np.nan)
                var_store['GJR-SkewT'][alpha]['actual'].append(actual_return)

        # ---- Method 3: RS⁻ Normal VaR (K454 winner) ----
        decay = 0.94
        sq_neg = np.where(is_returns < 0, is_returns**2, 0.0)
        ewma_rs = 0.0
        for k in range(len(sq_neg)):
            ewma_rs = decay * ewma_rs + (1 - decay) * sq_neg[k]
        semivar_vol = np.sqrt(ewma_rs * 2)  # scale to full variance

        for alpha in ALPHA_LEVELS:
            z = stats.norm.ppf(alpha)
            var_f = z * semivar_vol  # mean ≈ 0
            var_store['RS_neg-Normal'][alpha]['var'].append(var_f)
            var_store['RS_neg-Normal'][alpha]['actual'].append(actual_return)

        # ---- Method 4: HAR Log-Range VaR (NEW) ----
        # Use feature data for HAR estimation
        # Find matching feature window
        date_t = returns_idx[t_idx]
        feat_before = feat.loc[feat.index < date_t]

        if len(feat_before) >= HAR_MIN_WINDOW:
            har_window = feat_before.iloc[-ROLLING_WINDOW:] if len(feat_before) >= ROLLING_WINDOW else feat_before
            har_sigma = har_log_range_vol(har_window)
        else:
            har_sigma = np.nan

        for alpha in ALPHA_LEVELS:
            if not np.isnan(har_sigma):
                z = stats.norm.ppf(alpha)
                var_f = z * har_sigma  # mean ≈ 0
            else:
                var_f = np.nan
            var_store['HAR-Range-Normal'][alpha]['var'].append(var_f)
            var_store['HAR-Range-Normal'][alpha]['actual'].append(actual_return)

        # ---- Method 5: HAR + Semi Combined VaR ----
        for alpha in ALPHA_LEVELS:
            if not np.isnan(har_sigma) and not np.isnan(semivar_vol):
                combined_vol = 0.5 * har_sigma + 0.5 * semivar_vol
                z = stats.norm.ppf(alpha)
                var_f = z * combined_vol
            else:
                var_f = np.nan
            var_store['HAR+Semi-Combined'][alpha]['var'].append(var_f)
            var_store['HAR+Semi-Combined'][alpha]['actual'].append(actual_return)

        # ---- Method 6: Hybrid GARCH + HAR ----
        for alpha in ALPHA_LEVELS:
            if not np.isnan(gjr_cond_vol) and not np.isnan(har_sigma):
                hybrid_vol = 0.5 * gjr_cond_vol + 0.5 * har_sigma
                z = stats.norm.ppf(alpha)
                var_f = gjr_cond_mean / 2 + z * hybrid_vol  # partial mean from GARCH
            else:
                var_f = np.nan
            var_store['Hybrid-GARCH+HAR'][alpha]['var'].append(var_f)
            var_store['Hybrid-GARCH+HAR'][alpha]['actual'].append(actual_return)

    # ---- Run Trinity Tests ----
    asset_results = {
        'diagnostics': diagnostics_all[ticker],
        'n_oos': n_oos,
        'oos_range': f"{returns_idx[oos_start_idx].date()} to {returns_idx[oos_end_idx-1].date()}",
        'methods': {},
    }

    print(f"\n  --- Trinity Test Results for {ticker} ---")
    print(f"  {'Method':<22} {'α':>4} {'Viol':>6} {'Rate':>7} {'Kup':>6} {'Chr':>6} {'DQ':>6} {'Trinity':>8}")
    print(f"  {'-'*65}")

    for method in METHODS:
        method_results = {}
        for alpha in ALPHA_LEVELS:
            var_arr = np.array(var_store[method][alpha]['var'])
            act_arr = np.array(var_store[method][alpha]['actual'])

            # Remove NaN
            valid = ~np.isnan(var_arr)
            var_v = var_arr[valid]
            act_v = act_arr[valid]

            if len(var_v) < 50:
                method_results[f"{int(alpha*100)}%"] = {'error': f'too few valid obs ({len(var_v)})'}
                continue

            violations = (act_v < var_v).astype(int)
            result = run_trinity(violations, var_v, act_v, alpha)
            method_results[f"{int(alpha*100)}%"] = result

            # Print row
            kp = 'P' if result['kupiec']['p_value'] > 0.05 else 'F'
            cp = 'P' if result['christoffersen']['p_value'] > 0.05 else 'F'
            dp = 'P' if result['dq']['p_value'] > 0.05 else 'F'
            tp = 'PASS' if result['trinity_pass'] else 'FAIL'
            print(f"  {method:<22} {int(alpha*100):>3}% {result['n_violations']:>5}/{result['n_obs']} "
                  f"{result['violation_rate']:>6.3f}  {kp:>4}   {cp:>4}   {dp:>4}   {tp:>6}")

        asset_results['methods'][method] = method_results

    all_results[ticker] = asset_results


elapsed = time.time() - t_start
print(f"\n  Total runtime: {elapsed:.1f}s")


# ============================================================
# 7. CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("[5] CROSS-ASSET SUMMARY: Trinity Pass Count")
print("=" * 70)

# Count Trinity passes per method across all assets and alpha levels
# Maximum: 3 assets × 2 alpha levels = 6
summary_table = {}
for method in METHODS:
    passes_1pct = 0
    passes_5pct = 0
    total_pass = 0
    for ticker in ASSETS:
        if ticker not in all_results:
            continue
        m_res = all_results[ticker]['methods'].get(method, {})
        r1 = m_res.get('1%', {})
        r5 = m_res.get('5%', {})
        if r1.get('trinity_pass', False):
            passes_1pct += 1
            total_pass += 1
        if r5.get('trinity_pass', False):
            passes_5pct += 1
            total_pass += 1
    summary_table[method] = {
        'pass_1pct': passes_1pct,
        'pass_5pct': passes_5pct,
        'total_pass': total_pass,
        'total_possible': len(ASSETS) * 2,
    }

print(f"\n  {'Method':<22} {'1% Pass':>8} {'5% Pass':>8} {'Total':>8}")
print(f"  {'-'*50}")
for method in METHODS:
    s = summary_table[method]
    print(f"  {method:<22} {s['pass_1pct']:>5}/3   {s['pass_5pct']:>5}/3   {s['total_pass']:>5}/6")

# Find best method
best_method = max(summary_table, key=lambda m: summary_table[m]['total_pass'])
best_score = summary_table[best_method]['total_pass']
tied_best = [m for m in METHODS if summary_table[m]['total_pass'] == best_score]

print(f"\n  Best method(s): {', '.join(tied_best)} ({best_score}/6 Trinity passes)")


# ============================================================
# 8. KEY COMPARISONS
# ============================================================
print("\n" + "=" * 70)
print("[6] KEY COMPARISONS")
print("=" * 70)

# HAR vs RS⁻ (K454 winner)
har_total = summary_table['HAR-Range-Normal']['total_pass']
rs_total = summary_table['RS_neg-Normal']['total_pass']
gjr_normal_total = summary_table['GJR-Normal']['total_pass']
gjr_skewt_total = summary_table['GJR-SkewT']['total_pass']
combined_total = summary_table['HAR+Semi-Combined']['total_pass']
hybrid_total = summary_table['Hybrid-GARCH+HAR']['total_pass']

print(f"\n  HAR-Range-Normal vs RS⁻-Normal (K454 winner):")
print(f"    HAR:  {har_total}/6,  RS⁻: {rs_total}/6")
if har_total > rs_total:
    har_vs_rs = "HAR WINS — better vol forecaster → better VaR"
elif har_total == rs_total:
    har_vs_rs = "TIE — HAR matches RS⁻ despite different information"
else:
    har_vs_rs = "RS⁻ WINS — semivariance still superior for tail risk"

print(f"    Verdict: {har_vs_rs}")

print(f"\n  HAR-Range-Normal vs GJR-GARCH baselines:")
print(f"    HAR:        {har_total}/6")
print(f"    GJR-Normal: {gjr_normal_total}/6")
print(f"    GJR-SkewT:  {gjr_skewt_total}/6")

print(f"\n  Combined models:")
print(f"    HAR+Semi:    {combined_total}/6")
print(f"    GARCH+HAR:   {hybrid_total}/6")

# ============================================================
# 9. JUDGMENT
# ============================================================
print("\n" + "=" * 70)
print("[7] JUDGMENT")
print("=" * 70)

# Determine overall judgment
if har_total >= 5:
    judgment = "HAR-Range VaR EXCELLENT — passes Trinity ≥5/6, dominates alternatives"
elif har_total >= 4:
    judgment = "HAR-Range VaR GOOD — passes Trinity ≥4/6, competitive"
elif har_total >= 3:
    judgment = "HAR-Range VaR ADEQUATE — passes Trinity ≥3/6, comparable to alternatives"
elif har_total >= 1:
    judgment = "HAR-Range VaR MARGINAL — limited Trinity passes, not better than alternatives"
else:
    judgment = "HAR-Range VaR FAILS — does not pass Trinity test"

# Compare to K454 winner (RS⁻)
if har_total > rs_total:
    comparison_k454 = "IMPROVES on K454: HAR log-range VaR beats semivariance VaR"
elif har_total == rs_total:
    comparison_k454 = "MATCHES K454: HAR log-range VaR ties semivariance VaR"
else:
    comparison_k454 = "DOES NOT IMPROVE on K454: Semivariance VaR still better for tail risk"

# Key insight: best vol forecaster ≠ best VaR?
if har_total < rs_total:
    key_insight = ("IMPORTANT: Best vol forecaster (HAR, K465) does NOT automatically produce best VaR. "
                   "Semivariance captures downside risk directly, while HAR measures total range. "
                   "For tail risk, downside-specific information matters more than overall forecast accuracy.")
elif har_total > rs_total:
    key_insight = ("CONFIRMED: Best vol forecaster (HAR, K465) also produces best VaR. "
                   "Superior σ prediction translates to superior tail risk estimation.")
else:
    key_insight = ("NUANCED: Best vol forecaster (HAR, K465) produces comparable VaR to semivariance. "
                   "Both approaches capture tail risk adequately through different information channels.")

print(f"\n  {judgment}")
print(f"\n  K454 comparison: {comparison_k454}")
print(f"\n  Key insight: {key_insight}")


# ============================================================
# 10. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "K467",
    "title": "HAR Log-Range Based VaR Estimation",
    "background": (
        "K465: HAR log-range 10/10 cross-OOS (publication ready) — best vol forecaster. "
        "K454: Semivariance (RS⁻) VaR passes Trinity 3/3 at 1% (beats GARCH Skewed-t 1/3). "
        "Question: If HAR log-range is a better σ forecaster, does it produce better VaR?"
    ),
    "references": [
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Alizadeh, Brandt & Diebold (2002) JFE — Range-based vol estimation",
        "Kupiec (1995) — Unconditional coverage test",
        "Christoffersen (1998) — Independence test",
        "Engle & Manganelli (2004) — Dynamic Quantile test",
        "Patton & Sheppard (2015) — Semivariance decomposition",
        "K465 — HAR log-range cross-OOS validation (10/10)",
        "K454 — Semivariance VaR Trinity test (RS⁻ 3/3 wins)",
    ],
    "method": "Rolling window VaR backtest with Trinity test (Kupiec + Christoffersen + DQ)",
    "assets": ASSETS,
    "oos_period": f"{OOS_START} to {OOS_END}",
    "rolling_window": ROLLING_WINDOW,
    "var_methods": METHODS,
    "var_levels": ALPHA_LEVELS,
    "data_source": "yfinance (OHLC for range-based, Close for returns)",
    "results": all_results,
    "summary": {
        "trinity_pass_counts": summary_table,
        "best_method": tied_best if len(tied_best) > 1 else tied_best[0],
        "best_score": f"{best_score}/6",
    },
    "comparisons": {
        "har_vs_rs_neg": har_vs_rs,
        "har_vs_gjr_normal": f"HAR {har_total}/6 vs GJR-Normal {gjr_normal_total}/6",
        "har_vs_gjr_skewt": f"HAR {har_total}/6 vs GJR-SkewT {gjr_skewt_total}/6",
        "combined_models": f"HAR+Semi {combined_total}/6, GARCH+HAR {hybrid_total}/6",
        "k454_comparison": comparison_k454,
    },
    "judgment": judgment,
    "key_insight": key_insight,
    "limitations": [
        "OOS limited to 2023-2024 (2 years, ~502 days) — single regime",
        "HAR log-range uses Parkinson estimator which assumes no jumps",
        "RS⁻ scaling factor (×2) assumes approximate symmetry baseline",
        "EWMA lambda=0.94 (RiskMetrics standard) not optimized per asset",
        "Normal VaR assumption for HAR — could test Student-t or EVT overlay",
        "Only 3 assets (SPY, QQQ, EEM) — limited cross-asset validation",
    ],
    "runtime_seconds": round(elapsed, 1),
    "timestamp": datetime.now(timezone.utc).isoformat(),
}

output_path = "experiments/k467_har_range_var_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")

print("\n" + "=" * 70)
print("K467 COMPLETE")
print("=" * 70)
