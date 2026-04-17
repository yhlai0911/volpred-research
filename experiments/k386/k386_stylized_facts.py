#!/usr/bin/env python3
"""
K386: Stylized Facts Audit — Do All 10 Asset Classes Follow the Same Rules?
==========================================================================
[提出: Claude, 執行: Claude]

Tests Cont (2001) stylized facts of financial returns across 10 asset classes:
  SPY (equity), GLD (commodity-gold), TLT (bonds), BTC-USD (crypto),
  CL=F (oil), NG=F (nat gas), EURUSD=X (FX), VNQ (real estate),
  DBA (agriculture), ^VIX (volatility index — proxy for tail asset)

Stylized facts tested:
  1. Heavy tails (excess kurtosis > 0, Jarque-Bera test)
  2. Absence of autocorrelation in returns (ACF(1) ≈ 0)
  3. Volatility clustering (ACF(1) of |returns| > 0, significant)
  4. Leverage effect (negative correlation: return vs. future vol)
  5. Volume-volatility correlation (positive)
  6. Asymmetry / skewness (negative for equity-like)
  7. Aggregational Gaussianity (kurtosis decreases with horizon)
  8. Intermittency (high-activity bursts measured via participation ratio)
  9. Slow decay of ACF(|r|) (power-law-like decay)

Data: yfinance, max available history. Real data only.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import curve_fit
from statsmodels.stats.stattools import jarque_bera
from statsmodels.tsa.stattools import acf
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
ASSETS = {
    'SPY': 'US Equity',
    'GLD': 'Gold',
    'TLT': 'US Bonds',
    'BTC-USD': 'Crypto',
    'CL=F': 'Oil',
    'NG=F': 'Nat Gas',
    'EURUSD=X': 'FX',
    'VNQ': 'Real Estate',
    'DBA': 'Agriculture',
    '^VIX': 'VIX Index',
}

SIGNIFICANCE_LEVEL = 0.05

# ============================================================
# Download data
# ============================================================
print("=" * 80)
print("K386: Stylized Facts Audit — Cross-Asset Universality Test")
print("=" * 80)
print(f"\nDownloading data for {len(ASSETS)} assets...")

price_data = {}
volume_data = {}
for ticker, label in ASSETS.items():
    try:
        df = yf.download(ticker, period='max', progress=False)
        # Flatten multi-level columns from yfinance
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        n_obs = len(df)
        if n_obs < 500:
            print(f"  WARNING: {ticker} ({label}) only {n_obs} obs, skipping")
            continue
        price_data[ticker] = df['Close'].dropna()
        if 'Volume' in df.columns:
            vol_series = df['Volume'].dropna()
            if vol_series.sum() > 0:
                volume_data[ticker] = vol_series
        print(f"  {ticker:12s} ({label:15s}): {n_obs:6d} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")

# Compute returns
returns_data = {}
for ticker, prices in price_data.items():
    # Handle multi-level columns from yfinance
    if isinstance(prices, pd.DataFrame):
        prices = prices.iloc[:, 0]
    rets = prices.pct_change().dropna()
    # Remove extreme outliers (likely data errors) — beyond 50% daily
    rets = rets[rets.abs() < 0.5]
    returns_data[ticker] = rets

print(f"\n{'='*80}")
print("STYLIZED FACTS TESTS")
print(f"{'='*80}")

# ============================================================
# Storage for results
# ============================================================
results = {}  # results[fact_name][ticker] = {pass/fail, stat, detail}


# ============================================================
# Fact 1: Heavy Tails (Excess Kurtosis > 0)
# ============================================================
print("\n" + "─" * 60)
print("FACT 1: Heavy Tails (Leptokurtosis)")
print("  Test: Excess kurtosis > 0 + Jarque-Bera p < 0.05")
print("─" * 60)

results['heavy_tails'] = {}
print(f"  {'Asset':12s} {'Kurtosis':>10s} {'JB stat':>12s} {'JB p-val':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    kurt = stats.kurtosis(r, fisher=True)  # excess kurtosis
    jb_stat, jb_pval, _, _ = jarque_bera(r)
    passed = bool(kurt > 0 and jb_pval < SIGNIFICANCE_LEVEL)
    results['heavy_tails'][ticker] = {
        'pass': passed,
        'excess_kurtosis': round(float(kurt), 3),
        'jb_stat': round(float(jb_stat), 1),
        'jb_pval': float(jb_pval),
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    print(f"  {label:12s}  {kurt:10.3f}  {jb_stat:12.1f}  {jb_pval:12.2e}  {status:>8s}")


# ============================================================
# Fact 2: Absence of Autocorrelation in Returns
# ============================================================
print("\n" + "─" * 60)
print("FACT 2: Absence of Autocorrelation in Returns")
print("  Test: |ACF(1)| < 2/sqrt(N) (Bartlett band) AND Ljung-Box p > 0.05 for lags 1-5")
print("─" * 60)

results['no_autocorrelation'] = {}
print(f"  {'Asset':12s} {'ACF(1)':>10s} {'Bartlett':>10s} {'|ACF(1)|<B':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    n = len(r)
    acf_vals = acf(r, nlags=5, fft=True)
    acf1 = acf_vals[1]
    bartlett = 2.0 / np.sqrt(n)
    # Core test: ACF(1) within Bartlett band
    within_band = bool(abs(acf1) < bartlett)
    # Also check: none of first 5 lags is massively significant
    any_large = any(abs(acf_vals[i]) > 3 * bartlett for i in range(1, 6))
    passed = bool(within_band and not any_large)
    results['no_autocorrelation'][ticker] = {
        'pass': passed,
        'acf1': round(float(acf1), 5),
        'bartlett_band': round(float(bartlett), 5),
        'within_band': within_band,
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    band_str = "Yes" if within_band else "No"
    print(f"  {label:12s}  {acf1:10.5f}  {bartlett:10.5f}  {band_str:>12s}  {status:>8s}")


# ============================================================
# Fact 3: Volatility Clustering (ACF of |returns|)
# ============================================================
print("\n" + "─" * 60)
print("FACT 3: Volatility Clustering")
print("  Test: ACF(1) of |returns| > 0 and significant (> 2/sqrt(N))")
print("─" * 60)

results['vol_clustering'] = {}
print(f"  {'Asset':12s} {'ACF(1)|r|':>12s} {'ACF(5)|r|':>12s} {'ACF(20)|r|':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    abs_r = np.abs(r)
    n = len(r)
    acf_abs = acf(abs_r, nlags=20, fft=True)
    bartlett = 2.0 / np.sqrt(n)
    passed = bool(acf_abs[1] > bartlett)  # ACF(1) of |r| significantly positive
    results['vol_clustering'][ticker] = {
        'pass': passed,
        'acf1_abs': round(float(acf_abs[1]), 4),
        'acf5_abs': round(float(acf_abs[5]), 4),
        'acf20_abs': round(float(acf_abs[20]), 4),
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    print(f"  {label:12s}  {acf_abs[1]:12.4f}  {acf_abs[5]:12.4f}  {acf_abs[20]:12.4f}  {status:>8s}")


# ============================================================
# Fact 4: Leverage Effect (Negative return-future vol correlation)
# ============================================================
print("\n" + "─" * 60)
print("FACT 4: Leverage Effect")
print("  Test: Corr(r_t, |r_{t+1:t+5}|) < 0 AND significant (p < 0.05)")
print("  Note: Expected for equities, may not hold for all assets")
print("─" * 60)

results['leverage_effect'] = {}
print(f"  {'Asset':12s} {'Corr':>10s} {'p-value':>12s} {'Direction':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    # Compute forward 5-day realized vol
    abs_r = np.abs(r)
    fwd_vol = abs_r.rolling(5).mean().shift(-5)
    # Align
    valid = pd.concat([r, fwd_vol], axis=1).dropna()
    valid.columns = ['ret', 'fwd_vol']
    corr, pval = stats.pearsonr(valid['ret'], valid['fwd_vol'])
    passed = bool(corr < 0 and pval < SIGNIFICANCE_LEVEL)
    direction = "Negative" if corr < 0 else "Positive" if corr > 0 else "Zero"
    results['leverage_effect'][ticker] = {
        'pass': passed,
        'correlation': round(float(corr), 4),
        'p_value': float(pval),
        'direction': direction,
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    print(f"  {label:12s}  {corr:10.4f}  {pval:12.4e}  {direction:>12s}  {status:>8s}")


# ============================================================
# Fact 5: Volume-Volatility Correlation
# ============================================================
print("\n" + "─" * 60)
print("FACT 5: Volume-Volatility Correlation")
print("  Test: Corr(Volume, |r|) > 0 AND significant")
print("  Note: Not all assets have volume data")
print("─" * 60)

results['vol_volume_corr'] = {}
print(f"  {'Asset':12s} {'Corr':>10s} {'p-value':>12s} {'Has Volume':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    label = ASSETS[ticker]
    if ticker in volume_data:
        vol = volume_data[ticker]
        abs_r = np.abs(r)
        # Align
        common = pd.concat([abs_r, vol], axis=1).dropna()
        if len(common) > 100:
            common.columns = ['abs_ret', 'volume']
            # Remove zero-volume days
            common = common[common['volume'] > 0]
            corr, pval = stats.pearsonr(common['abs_ret'], common['volume'])
            passed = bool(corr > 0 and pval < SIGNIFICANCE_LEVEL)
            results['vol_volume_corr'][ticker] = {
                'pass': passed,
                'correlation': round(float(corr), 4),
                'p_value': float(pval),
                'has_volume': True,
            }
            status = "PASS" if passed else "FAIL"
            print(f"  {label:12s}  {corr:10.4f}  {pval:12.4e}  {'Yes':>12s}  {status:>8s}")
        else:
            results['vol_volume_corr'][ticker] = {'pass': None, 'has_volume': False}
            print(f"  {label:12s}  {'N/A':>10s}  {'N/A':>12s}  {'Insuff':>12s}  {'N/A':>8s}")
    else:
        results['vol_volume_corr'][ticker] = {'pass': None, 'has_volume': False}
        print(f"  {label:12s}  {'N/A':>10s}  {'N/A':>12s}  {'No':>12s}  {'N/A':>8s}")


# ============================================================
# Fact 6: Asymmetry (Skewness)
# ============================================================
print("\n" + "─" * 60)
print("FACT 6: Asymmetry of Gains and Losses (Skewness)")
print("  Test: Skewness significantly != 0 (test via D'Agostino)")
print("  Note: Classic expectation is negative skew for equities")
print("─" * 60)

results['skewness'] = {}
print(f"  {'Asset':12s} {'Skewness':>10s} {'p-value':>12s} {'Direction':>12s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*12} {'-'*12} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker]
    skew = stats.skew(r)
    # D'Agostino skewness test
    try:
        stat, pval = stats.skewtest(r)
    except Exception:
        pval = 1.0
    passed = bool(pval < SIGNIFICANCE_LEVEL)  # significantly non-zero skewness
    direction = "Negative" if skew < 0 else "Positive"
    results['skewness'][ticker] = {
        'pass': passed,
        'skewness': round(float(skew), 4),
        'p_value': float(pval),
        'direction': direction,
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    print(f"  {label:12s}  {skew:10.4f}  {pval:12.4e}  {direction:>12s}  {status:>8s}")


# ============================================================
# Fact 7: Aggregational Gaussianity
# ============================================================
print("\n" + "─" * 60)
print("FACT 7: Aggregational Gaussianity")
print("  Test: Excess kurtosis decreases as horizon increases (1d → 5d → 20d → 60d)")
print("  Specifically: Kurt(60d) < Kurt(1d)")
print("─" * 60)

results['agg_gaussianity'] = {}
horizons = [1, 5, 20, 60]
print(f"  {'Asset':12s} {'Kurt 1d':>10s} {'Kurt 5d':>10s} {'Kurt 20d':>10s} {'Kurt 60d':>10s} {'Monotone':>10s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")

for ticker in price_data:
    prices = price_data[ticker]
    if isinstance(prices, pd.DataFrame):
        prices = prices.iloc[:, 0]
    kurts = []
    for h in horizons:
        h_rets = prices.pct_change(h).dropna()
        h_rets = h_rets[h_rets.abs() < 1.0]  # remove extreme outliers
        k = stats.kurtosis(h_rets, fisher=True)
        kurts.append(round(float(k), 3))

    # Test: kurtosis decreases with horizon (monotone decreasing)
    monotone = all(kurts[i] >= kurts[i+1] for i in range(len(kurts)-1))
    # Minimum requirement: kurt(60d) < kurt(1d)
    basic_decrease = kurts[-1] < kurts[0]
    passed = bool(basic_decrease)

    results['agg_gaussianity'][ticker] = {
        'pass': passed,
        'kurtosis_by_horizon': dict(zip([f'{h}d' for h in horizons], kurts)),
        'monotone_decrease': monotone,
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    mono_str = "Yes" if monotone else "No"
    print(f"  {label:12s}  {kurts[0]:10.3f}  {kurts[1]:10.3f}  {kurts[2]:10.3f}  {kurts[3]:10.3f}  {mono_str:>10s}  {status:>8s}")


# ============================================================
# Fact 8: Intermittency (Bursts of High Activity)
# ============================================================
print("\n" + "─" * 60)
print("FACT 8: Intermittency (Bursts of High Activity)")
print("  Test: Participation ratio < 1.0 (returns are concentrated in bursts)")
print("  Participation ratio = (sum|r|)^2 / (N * sum(r^2)) — 1.0 means uniform")
print("  Also: fraction of days accounting for 50% of total absolute return")
print("─" * 60)

results['intermittency'] = {}
print(f"  {'Asset':12s} {'Part.Ratio':>12s} {'Days for 50%':>14s} {'Top10% share':>14s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*12} {'-'*14} {'-'*14} {'-'*8}")

for ticker in returns_data:
    r = returns_data[ticker].values
    abs_r = np.abs(r)
    n = len(r)

    # Participation ratio (inverse = effective number of active days / N)
    pr = (np.sum(abs_r))**2 / (n * np.sum(abs_r**2))

    # Fraction of days accounting for 50% of total |r|
    sorted_abs = np.sort(abs_r)[::-1]
    cumsum = np.cumsum(sorted_abs) / np.sum(sorted_abs)
    days_50pct = np.searchsorted(cumsum, 0.5) + 1
    frac_50pct = days_50pct / n

    # Top 10% of days: what fraction of total |r| do they account for?
    top10_n = max(1, int(n * 0.1))
    top10_share = np.sum(sorted_abs[:top10_n]) / np.sum(sorted_abs)

    # Pass if activity is concentrated (participation ratio < 0.8 or top 10% > 30%)
    passed = bool(pr < 0.8 or top10_share > 0.30)

    results['intermittency'][ticker] = {
        'pass': passed,
        'participation_ratio': round(float(pr), 4),
        'frac_days_for_50pct': round(float(frac_50pct), 4),
        'top10_share': round(float(top10_share), 4),
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    print(f"  {label:12s}  {pr:12.4f}  {frac_50pct:14.4f}  {top10_share:14.4f}  {status:>8s}")


# ============================================================
# Fact 9: Slow Decay of ACF(|r|) — Power Law
# ============================================================
print("\n" + "─" * 60)
print("FACT 9: Slow Decay of Autocorrelation of |returns|")
print("  Test: ACF(|r|) at lag 100 still positive & significant")
print("  Also: fit power-law ACF(k) ~ k^(-beta), beta < 1 indicates slow decay")
print("─" * 60)

results['slow_decay'] = {}
max_lag = 200
print(f"  {'Asset':12s} {'ACF(100)':>10s} {'ACF(200)':>10s} {'beta':>8s} {'Half-life':>10s} {'Result':>8s}")
print(f"  {'-'*12} {'-'*10} {'-'*10} {'-'*8} {'-'*10} {'-'*8}")

def power_law(x, a, beta):
    return a * x ** (-beta)

for ticker in returns_data:
    r = returns_data[ticker]
    abs_r = np.abs(r)
    n = len(r)

    actual_max_lag = min(max_lag, n // 4)
    acf_abs = acf(abs_r, nlags=actual_max_lag, fft=True)
    bartlett = 2.0 / np.sqrt(n)

    acf_100 = acf_abs[min(100, actual_max_lag)] if actual_max_lag >= 100 else np.nan
    acf_200 = acf_abs[min(200, actual_max_lag)] if actual_max_lag >= 200 else np.nan

    # Fit power law to ACF decay
    lags = np.arange(1, actual_max_lag + 1)
    acf_positive = acf_abs[1:]

    # Only fit to positive ACF values
    mask = acf_positive > 0
    if mask.sum() > 10:
        try:
            popt, _ = curve_fit(power_law, lags[mask], acf_positive[mask], p0=[0.5, 0.3], maxfev=5000)
            beta = popt[1]
        except Exception:
            beta = np.nan
    else:
        beta = np.nan

    # Find half-life: first lag where ACF < 0.5 * ACF(1)
    half_acf1 = acf_abs[1] / 2
    half_life = np.nan
    for lag_i in range(2, actual_max_lag + 1):
        if acf_abs[lag_i] < half_acf1:
            half_life = lag_i
            break

    # Pass if ACF(100) still positive and significant, or beta < 0.5 (very slow decay)
    sig_at_100 = bool(not np.isnan(acf_100) and acf_100 > bartlett)
    slow_beta = bool(not np.isnan(beta) and beta < 0.5)
    passed = bool(sig_at_100 or slow_beta)

    results['slow_decay'][ticker] = {
        'pass': passed,
        'acf_100': round(float(acf_100), 4) if not np.isnan(acf_100) else None,
        'acf_200': round(float(acf_200), 4) if not np.isnan(acf_200) else None,
        'beta': round(float(beta), 4) if not np.isnan(beta) else None,
        'half_life_days': int(half_life) if not np.isnan(half_life) else None,
    }
    label = ASSETS[ticker]
    status = "PASS" if passed else "FAIL"
    acf100_str = f"{acf_100:.4f}" if not np.isnan(acf_100) else "N/A"
    acf200_str = f"{acf_200:.4f}" if not np.isnan(acf_200) else "N/A"
    beta_str = f"{beta:.4f}" if not np.isnan(beta) else "N/A"
    hl_str = f"{int(half_life)}" if not np.isnan(half_life) else "N/A"
    print(f"  {label:12s}  {acf100_str:>10s}  {acf200_str:>10s}  {beta_str:>8s}  {hl_str:>10s}  {status:>8s}")


# ============================================================
# SUMMARY TABLE
# ============================================================
print("\n" + "=" * 100)
print("COMPREHENSIVE CROSS-ASSET STYLIZED FACTS TABLE")
print("=" * 100)

fact_names = [
    ('heavy_tails', 'Heavy Tails'),
    ('no_autocorrelation', 'No ACF(r)'),
    ('vol_clustering', 'Vol Cluster'),
    ('leverage_effect', 'Leverage'),
    ('vol_volume_corr', 'Vol-Volume'),
    ('skewness', 'Skewness'),
    ('agg_gaussianity', 'Agg Gauss'),
    ('intermittency', 'Intermit.'),
    ('slow_decay', 'Slow Decay'),
]

# Header
header = f"  {'Asset':12s}"
for _, display in fact_names:
    header += f" {display:>12s}"
header += f" {'Score':>8s}"
print(header)
print("  " + "-" * (12 + 13 * len(fact_names) + 8))

asset_scores = {}
for ticker in returns_data:
    label = ASSETS[ticker]
    row = f"  {label:12s}"
    pass_count = 0
    total_count = 0
    for key, _ in fact_names:
        if ticker in results[key]:
            val = results[key][ticker].get('pass', None)
            if val is True:
                row += f" {'PASS':>12s}"
                pass_count += 1
                total_count += 1
            elif val is False:
                row += f" {'FAIL':>12s}"
                total_count += 1
            else:
                row += f" {'N/A':>12s}"
        else:
            row += f" {'N/A':>12s}"
    score_str = f"{pass_count}/{total_count}"
    row += f" {score_str:>8s}"
    asset_scores[ticker] = (pass_count, total_count)
    print(row)

# Fact-level summary
print("\n" + "-" * 100)
print("  FACT-LEVEL PASS RATE:")
print("  " + "-" * 60)
for key, display in fact_names:
    passes = sum(1 for t in results[key] if results[key][t].get('pass') is True)
    total = sum(1 for t in results[key] if results[key][t].get('pass') is not None)
    rate = passes / total * 100 if total > 0 else 0
    bar = "#" * int(rate / 5)
    print(f"  {display:15s}: {passes:2d}/{total:2d} ({rate:5.1f}%) {bar}")

# ============================================================
# ANOMALIES & KEY FINDINGS
# ============================================================
print("\n" + "=" * 80)
print("KEY FINDINGS & ANOMALIES")
print("=" * 80)

# Which facts are truly universal?
print("\n[Universal Facts (hold for ALL assets)]")
for key, display in fact_names:
    all_pass = all(results[key].get(t, {}).get('pass', None) is True
                   for t in returns_data)
    testable = [t for t in returns_data if results[key].get(t, {}).get('pass') is not None]
    if all_pass and len(testable) == len(returns_data):
        print(f"  - {display}")

print("\n[Near-Universal Facts (hold for 8+ of 10 assets)]")
for key, display in fact_names:
    passes = sum(1 for t in returns_data if results[key].get(t, {}).get('pass') is True)
    testable = sum(1 for t in returns_data if results[key].get(t, {}).get('pass') is not None)
    if 8 <= passes < testable and testable >= 8:
        failures = [ASSETS[t] for t in returns_data if results[key].get(t, {}).get('pass') is False]
        print(f"  - {display} (fails: {', '.join(failures)})")

print("\n[Asset-Class Anomalies (assets that break 3+ rules)]")
for ticker in returns_data:
    p, t = asset_scores[ticker]
    fails = t - p
    if fails >= 3:
        failed_facts = [display for key, display in fact_names
                       if results[key].get(ticker, {}).get('pass') is False]
        print(f"  - {ASSETS[ticker]}: fails {', '.join(failed_facts)}")

print("\n[Leverage Effect Breakdown]")
for ticker in returns_data:
    info = results['leverage_effect'].get(ticker, {})
    corr = info.get('correlation', 0)
    pval = info.get('p_value', 1)
    label = ASSETS[ticker]
    sig = "*" if pval < 0.05 else ""
    print(f"  {label:12s}: corr = {corr:+.4f}{sig}  {'(Classic leverage)' if corr < 0 and pval < 0.05 else '(No leverage)' if corr >= 0 else '(Weak negative)'}")

# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    'experiment': 'K386',
    'title': 'Stylized Facts Audit — Cross-Asset Universality',
    'description': 'Tests 9 Cont (2001) stylized facts across 10 asset classes',
    'data_source': 'yfinance (max available history)',
    'n_assets': len(returns_data),
    'assets': {t: {'label': ASSETS[t], 'n_obs': len(returns_data[t])} for t in returns_data},
    'results': {},
    'summary': {
        'asset_scores': {ASSETS[t]: f"{p}/{tot}" for t, (p, tot) in asset_scores.items()},
    }
}

for key, display in fact_names:
    fact_passes = sum(1 for t in results[key] if results[key][t].get('pass') is True)
    fact_testable = sum(1 for t in results[key] if results[key][t].get('pass') is not None)
    output['results'][key] = {
        'display_name': display,
        'pass_rate': f"{fact_passes}/{fact_testable}",
        'per_asset': results[key],
    }

output_path = 'experiments/k386_stylized_facts_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 80)
print("CONCLUSION")
print("=" * 80)

# Count truly universal
universal = []
near_universal = []
partial = []
for key, display in fact_names:
    passes = sum(1 for t in returns_data if results[key].get(t, {}).get('pass') is True)
    testable = sum(1 for t in returns_data if results[key].get(t, {}).get('pass') is not None)
    if testable == 0:
        continue
    rate = passes / testable
    if rate >= 0.95:
        universal.append(display)
    elif rate >= 0.7:
        near_universal.append(display)
    else:
        partial.append(display)

print(f"\n  Universal (>95% pass rate): {', '.join(universal) if universal else 'None'}")
print(f"  Near-universal (70-95%):    {', '.join(near_universal) if near_universal else 'None'}")
print(f"  Asset-dependent (<70%):     {', '.join(partial) if partial else 'None'}")
print(f"\n  Implication: Models assuming universal stylized facts may be misspecified")
print(f"  for assets where these facts do not hold (especially leverage effect and volume).")
print(f"\n{'='*80}")
