#!/usr/bin/env python3
"""
K117: Climate/Weather Event Impact on Volatility
=================================================
跳躍式探索：氣候金融方向

問題：極端天氣事件是否影響特定資產的波動率？
方法：用市場數據 proxy 推斷天氣事件（不需真實天氣數據）

Proxies:
- KIE (保險 ETF) 大跌但 SPY 正常 → 天災保險理賠事件
- XLE (能源 ETF) 異常波動 → 能源/天氣事件
- DBA (農產品 ETF) spike → 農業天氣衝擊
- VIX spike + XLE spike 同時 → 天氣/能源危機

[提出: Claude (面向G跳躍探索), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K117: Climate/Weather Event Impact on Volatility")
print("=" * 70)

tickers = {
    'SPY': 'S&P 500 (Benchmark)',
    'KIE': 'Insurance ETF (天災 proxy)',
    'XLE': 'Energy ETF (能源天氣 proxy)',
    'DBA': 'Agriculture ETF (農業天氣 proxy)',
    '^VIX': 'VIX (Fear gauge)',
}

print("\n[1] Downloading data 2010-2024...")
data = {}
for ticker, desc in tickers.items():
    try:
        df = yf.download(ticker, start='2010-01-01', end='2024-12-31',
                         progress=False, auto_adjust=True)
        if len(df) > 0:
            # Handle both old and new yfinance column formats
            close = df['Close']
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            data[ticker] = close
            print(f"  {ticker}: {len(df)} days ({desc})")
        else:
            print(f"  {ticker}: NO DATA")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

# Align all series
prices = pd.DataFrame(data).dropna()
print(f"\nAligned dataset: {len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}")

# Calculate returns
returns = prices.pct_change().dropna()
print(f"Returns: {len(returns)} observations")

# ============================================================
# 2. Excess Return Calculation & Event Identification
# ============================================================
print("\n" + "=" * 70)
print("[2] Event Identification via Market-Based Proxies")
print("=" * 70)

# Excess returns relative to SPY
excess_returns = pd.DataFrame()
for ticker in ['KIE', 'XLE', 'DBA']:
    excess_returns[f'{ticker}_excess'] = returns[ticker] - returns['SPY']

# Also compute raw absolute returns for each
abs_returns = returns[['KIE', 'XLE', 'DBA', 'SPY']].abs()

# Rolling 22-day realized vol (annualized)
rv_22 = returns[['KIE', 'XLE', 'DBA', 'SPY']].rolling(22).std() * np.sqrt(252)

# VIX level
vix = prices['^VIX']

# ---- Event Type 1: Insurance Disaster (KIE crash, SPY neutral) ----
kie_excess = excess_returns['KIE_excess']
kie_excess_mean = kie_excess.mean()
kie_excess_std = kie_excess.std()

# KIE drops significantly more than SPY (2σ negative excess)
insurance_events = (kie_excess < kie_excess_mean - 2 * kie_excess_std)
# Additional filter: SPY not in major crash (SPY return > -2%)
insurance_events = insurance_events & (returns['SPY'] > -0.02)

print(f"\nEvent Type 1: Insurance Disaster Proxy (KIE excess < -2σ, SPY > -2%)")
print(f"  Threshold: KIE excess return < {kie_excess_mean - 2 * kie_excess_std:.4f}")
print(f"  Events identified: {insurance_events.sum()}")

# ---- Event Type 2: Energy Weather Event (XLE spike or crash) ----
xle_excess = excess_returns['XLE_excess']
xle_excess_mean = xle_excess.mean()
xle_excess_std = xle_excess.std()

# XLE moves significantly vs SPY (|excess| > 2σ)
energy_events = (xle_excess.abs() > xle_excess_mean + 2 * xle_excess_std)
# Filter: not during broad market crash
energy_events = energy_events & (returns['SPY'].abs() < 0.03)

print(f"\nEvent Type 2: Energy/Weather Event Proxy (|XLE excess| > 2σ, |SPY| < 3%)")
print(f"  Threshold: |XLE excess return| > {xle_excess_mean + 2 * xle_excess_std:.4f}")
print(f"  Events identified: {energy_events.sum()}")

# ---- Event Type 3: Agriculture Weather Shock (DBA spike) ----
dba_excess = excess_returns['DBA_excess']
dba_excess_mean = dba_excess.mean()
dba_excess_std = dba_excess.std()

# DBA positive excess > 2σ (price spike from supply disruption)
agri_events = (dba_excess > dba_excess_mean + 2 * dba_excess_std)

print(f"\nEvent Type 3: Agriculture Weather Shock Proxy (DBA excess > +2σ)")
print(f"  Threshold: DBA excess return > {dba_excess_mean + 2 * dba_excess_std:.4f}")
print(f"  Events identified: {agri_events.sum()}")

# ---- Event Type 4: Combined Climate Crisis (VIX spike + XLE spike) ----
vix_change = vix.pct_change().reindex(returns.index)
vix_spike = vix_change > vix_change.mean() + 2 * vix_change.std()
xle_abs_spike = returns['XLE'].abs() > returns['XLE'].abs().mean() + 2 * returns['XLE'].abs().std()
climate_crisis = vix_spike & xle_abs_spike

print(f"\nEvent Type 4: Combined Climate Crisis (VIX spike + XLE spike)")
print(f"  Events identified: {climate_crisis.sum()}")

# Summary table
event_types = {
    'Insurance Disaster': insurance_events,
    'Energy Weather': energy_events,
    'Agriculture Shock': agri_events,
    'Combined Crisis': climate_crisis,
}

print("\n--- Event Summary ---")
print(f"{'Event Type':<25} {'Count':>6} {'Freq/yr':>8} {'First':>12} {'Last':>12}")
print("-" * 70)
for name, mask in event_types.items():
    n = mask.sum()
    years = (returns.index[-1] - returns.index[0]).days / 365.25
    freq = n / years
    if n > 0:
        first = returns.index[mask].min().strftime('%Y-%m-%d')
        last = returns.index[mask].max().strftime('%Y-%m-%d')
    else:
        first = last = 'N/A'
    print(f"  {name:<23} {n:>6} {freq:>8.1f} {first:>12} {last:>12}")

# ============================================================
# 3. Post-Event Volatility Response
# ============================================================
print("\n" + "=" * 70)
print("[3] Post-Event Volatility Response Analysis")
print("=" * 70)

def analyze_post_event_vol(returns_series, event_mask, horizons=[1, 5, 22],
                            series_name='', n_bootstrap=5000):
    """
    Compare realized volatility after events vs non-events.
    Returns dict with stats for each horizon.
    """
    results = {}

    for h in horizons:
        # Forward realized vol (annualized)
        fwd_vol = returns_series.rolling(h).std().shift(-h) * np.sqrt(252)

        event_vol = fwd_vol[event_mask].dropna()
        non_event_vol = fwd_vol[~event_mask].dropna()

        if len(event_vol) < 10:
            results[h] = {'n_events': len(event_vol), 'insufficient': True}
            continue

        # Welch's t-test (unequal variance)
        t_stat, p_val = stats.ttest_ind(event_vol, non_event_vol, equal_var=False)

        # Effect size (Cohen's d)
        pooled_std = np.sqrt((event_vol.var() + non_event_vol.var()) / 2)
        cohens_d = (event_vol.mean() - non_event_vol.mean()) / pooled_std if pooled_std > 0 else 0

        # Bootstrap CI for mean difference
        diffs = []
        np.random.seed(42)
        for _ in range(n_bootstrap):
            boot_event = np.random.choice(event_vol.values, size=len(event_vol), replace=True)
            boot_non = np.random.choice(non_event_vol.values, size=len(non_event_vol), replace=True)
            diffs.append(boot_event.mean() - boot_non.mean())
        ci_lo, ci_hi = np.percentile(diffs, [2.5, 97.5])

        results[h] = {
            'n_events': len(event_vol),
            'event_vol_mean': event_vol.mean(),
            'non_event_vol_mean': non_event_vol.mean(),
            'vol_ratio': event_vol.mean() / non_event_vol.mean() if non_event_vol.mean() > 0 else np.nan,
            't_stat': t_stat,
            'p_val': p_val,
            'cohens_d': cohens_d,
            'ci_lo': ci_lo,
            'ci_hi': ci_hi,
        }

    return results

# Analyze each event type for each asset
print(f"\n{'Event Type':<20} {'Asset':<6} {'H':>3} {'N':>5} {'Event Vol':>10} {'Normal Vol':>10} "
      f"{'Ratio':>6} {'t':>7} {'p':>8} {'d':>6} {'95% CI':>18}")
print("-" * 115)

all_results = {}

for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        print(f"  {event_name}: insufficient events ({event_mask.sum()}) — skipped")
        continue

    all_results[event_name] = {}

    for asset in ['SPY', 'KIE', 'XLE', 'DBA']:
        res = analyze_post_event_vol(returns[asset], event_mask,
                                      horizons=[1, 5, 22], series_name=asset)
        all_results[event_name][asset] = res

        for h, r in res.items():
            if r.get('insufficient'):
                continue
            sig = '***' if r['p_val'] < 0.001 else '**' if r['p_val'] < 0.01 else '*' if r['p_val'] < 0.05 else ''
            print(f"  {event_name:<18} {asset:<6} {h:>3}d {r['n_events']:>5} "
                  f"{r['event_vol_mean']:>9.1%} {r['non_event_vol_mean']:>9.1%} "
                  f"{r['vol_ratio']:>5.2f}x {r['t_stat']:>7.2f} {r['p_val']:>7.4f}{sig:3s} "
                  f"{r['cohens_d']:>5.2f} [{r['ci_lo']:>+.3f}, {r['ci_hi']:>+.3f}]")
    print()

# ============================================================
# 4. Cross-Asset Volatility Contagion
# ============================================================
print("\n" + "=" * 70)
print("[4] Cross-Asset Volatility Contagion from Climate Events")
print("=" * 70)

print("\nQuestion: Do climate-proxy events in one sector spread to broader market?")

# For insurance events: does KIE vol spike lead to SPY vol increase?
for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        continue

    print(f"\n--- {event_name} Events ---")

    # Compute vol change: post-event 5d vol minus pre-event 5d vol
    for target in ['SPY', 'KIE', 'XLE', 'DBA']:
        pre_vol = returns[target].rolling(5).std().shift(1) * np.sqrt(252)  # pre-event vol
        post_vol = returns[target].rolling(5).std().shift(-5) * np.sqrt(252)  # post-event vol
        vol_change = post_vol - pre_vol

        event_vol_change = vol_change[event_mask].dropna()
        non_event_vol_change = vol_change[~event_mask].dropna()

        if len(event_vol_change) < 10:
            continue

        t, p = stats.ttest_ind(event_vol_change, non_event_vol_change, equal_var=False)

        sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else ''
        print(f"  {target}: event ΔVol={event_vol_change.mean():+.3f}, "
              f"normal ΔVol={non_event_vol_change.mean():+.3f}, "
              f"t={t:.2f}, p={p:.4f}{sig}")

# Granger-like test: does lagged KIE vol predict SPY vol?
print("\n--- Granger-like Analysis: Sector vol → SPY vol (5-day lag) ---")
for sector in ['KIE', 'XLE', 'DBA']:
    sector_vol = returns[sector].rolling(5).std() * np.sqrt(252)
    spy_fwd_vol = returns['SPY'].rolling(5).std().shift(-5) * np.sqrt(252)

    # Remove NaN
    mask = sector_vol.notna() & spy_fwd_vol.notna()
    x = sector_vol[mask].values
    y = spy_fwd_vol[mask].values

    # Correlation
    corr, p_corr = stats.pearsonr(x, y)

    # Partial correlation controlling for current SPY vol
    spy_vol = returns['SPY'].rolling(5).std() * np.sqrt(252)
    z = spy_vol[mask].values

    # Partial corr: corr(x, y | z)
    from numpy.linalg import lstsq
    # Residualize x and y on z
    z_mat = np.column_stack([z, np.ones(len(z))])
    x_resid = x - z_mat @ lstsq(z_mat, x, rcond=None)[0]
    y_resid = y - z_mat @ lstsq(z_mat, y, rcond=None)[0]
    partial_corr, p_partial = stats.pearsonr(x_resid, y_resid)

    sig1 = '*' if p_corr < 0.05 else ''
    sig2 = '*' if p_partial < 0.05 else ''
    print(f"  {sector} vol → SPY fwd vol: r={corr:.3f} (p={p_corr:.4f}{sig1}), "
          f"partial r={partial_corr:.3f} (p={p_partial:.4f}{sig2})")

# ============================================================
# 5. Conditional Volatility: VIX-controlled Analysis
# ============================================================
print("\n" + "=" * 70)
print("[5] VIX-Controlled Analysis: Climate Events Beyond Market Fear")
print("=" * 70)

print("\nQuestion: After controlling for VIX, do climate events still predict excess vol?")

# Split into VIX regimes
vix_aligned = vix.reindex(returns.index).ffill()
vix_median = vix_aligned.median()

for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        continue

    print(f"\n--- {event_name} ---")

    # Low VIX regime
    low_vix = vix_aligned < vix_median
    high_vix = vix_aligned >= vix_median

    for regime_name, regime_mask in [('Low VIX', low_vix), ('High VIX', high_vix)]:
        combined = event_mask & regime_mask
        n_events_regime = combined.sum()

        if n_events_regime < 10:
            print(f"  {regime_name}: {n_events_regime} events (insufficient)")
            continue

        # 5-day forward SPY vol
        spy_fwd_vol = returns['SPY'].rolling(5).std().shift(-5) * np.sqrt(252)
        event_vol = spy_fwd_vol[combined].dropna()
        non_event_vol = spy_fwd_vol[regime_mask & ~event_mask].dropna()

        t, p = stats.ttest_ind(event_vol, non_event_vol, equal_var=False)
        sig = '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else ''

        print(f"  {regime_name} (n={n_events_regime}): event SPY vol={event_vol.mean():.1%}, "
              f"normal={non_event_vol.mean():.1%}, ratio={event_vol.mean()/non_event_vol.mean():.2f}x, "
              f"t={t:.2f}, p={p:.4f}{sig}")

# ============================================================
# 6. Long-Term Trend: Is Climate Impact Increasing?
# ============================================================
print("\n" + "=" * 70)
print("[6] Long-Term Trend: Is Climate Impact on Volatility Increasing?")
print("=" * 70)

print("\nQuestion: Are climate-proxy events becoming more frequent or impactful?")

# Split into sub-periods
periods = [
    ('2010-2014', '2010-01-01', '2014-12-31'),
    ('2015-2019', '2015-01-01', '2019-12-31'),
    ('2020-2024', '2020-01-01', '2024-12-31'),
]

print(f"\n{'Event Type':<25} {'Period':<12} {'Count':>6} {'Freq/yr':>8} "
      f"{'Avg |Excess|':>12} {'Avg Post Vol':>12}")
print("-" * 80)

trend_data = {}
for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        continue

    trend_data[event_name] = []

    for period_name, start, end in periods:
        period_mask = (returns.index >= start) & (returns.index <= end)
        n_period = period_mask.sum()
        n_events = (event_mask & period_mask).sum()
        years = n_period / 252
        freq = n_events / years if years > 0 else 0

        # Average magnitude of excess return during events
        if event_name == 'Insurance Disaster':
            excess = excess_returns['KIE_excess']
        elif event_name == 'Energy Weather':
            excess = excess_returns['XLE_excess']
        elif event_name == 'Agriculture Shock':
            excess = excess_returns['DBA_excess']
        else:
            excess = excess_returns['XLE_excess']

        event_excess = excess[event_mask & period_mask]
        avg_excess = event_excess.abs().mean() if len(event_excess) > 0 else np.nan

        # Average post-event 5d vol
        spy_fwd_vol = returns['SPY'].rolling(5).std().shift(-5) * np.sqrt(252)
        post_vol = spy_fwd_vol[event_mask & period_mask].mean()

        trend_data[event_name].append({
            'period': period_name,
            'count': int(n_events),
            'freq': freq,
            'avg_excess': avg_excess,
            'post_vol': post_vol,
        })

        print(f"  {event_name:<23} {period_name:<12} {n_events:>6} {freq:>8.1f} "
              f"{avg_excess:>11.2%} {post_vol:>11.1%}")
    print()

# Trend test: is event frequency increasing?
print("\n--- Trend Test (linear regression on annual event count) ---")
for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        continue

    # Annual event counts
    annual = event_mask.groupby(event_mask.index.year).sum()
    years = annual.index.values.astype(float)
    counts = annual.values.astype(float)

    if len(years) >= 5:
        slope, intercept, r_val, p_val, se = stats.linregress(years, counts)
        sig = '*' if p_val < 0.05 else ''
        print(f"  {event_name}: slope={slope:+.2f} events/year, R²={r_val**2:.3f}, p={p_val:.4f}{sig}")

        # Also test if severity is increasing
        # Average excess return magnitude per year
        if event_name == 'Insurance Disaster':
            excess = excess_returns['KIE_excess']
        elif event_name == 'Energy Weather':
            excess = excess_returns['XLE_excess']
        elif event_name == 'Agriculture Shock':
            excess = excess_returns['DBA_excess']
        else:
            excess = excess_returns['XLE_excess']

        annual_severity = excess.abs()[event_mask].groupby(event_mask.index[event_mask].year).mean()
        if len(annual_severity) >= 5:
            yrs = annual_severity.index.values.astype(float)
            sev = annual_severity.values
            slope_s, _, r_s, p_s, _ = stats.linregress(yrs, sev)
            sig_s = '*' if p_s < 0.05 else ''
            print(f"    Severity trend: slope={slope_s:+.5f}/year, R²={r_s**2:.3f}, p={p_s:.4f}{sig_s}")

# ============================================================
# 7. Sector-Specific Vol Clustering After Climate Events
# ============================================================
print("\n" + "=" * 70)
print("[7] Sector-Specific Volatility Clustering After Climate Events")
print("=" * 70)

for event_name, event_mask in event_types.items():
    if event_mask.sum() < 15:
        continue

    print(f"\n--- {event_name}: Cumulative Abnormal Vol (event study) ---")
    print(f"{'Asset':<6} {'Pre-5d Vol':>10} {'Day 1':>10} {'Day 5':>10} {'Day 10':>10} {'Day 22':>10} {'Persistent?':>12}")

    event_dates = returns.index[event_mask]

    for asset in ['SPY', 'KIE', 'XLE', 'DBA']:
        # Pre-event vol (5 days before)
        pre_vol = returns[asset].rolling(5).std() * np.sqrt(252)

        vols_at_horizons = {}
        for h in [1, 5, 10, 22]:
            fwd_vol = returns[asset].rolling(max(h, 2)).std().shift(-h) * np.sqrt(252)
            event_fwd = fwd_vol[event_mask].dropna()
            vols_at_horizons[h] = event_fwd.mean()

        pre = pre_vol[event_mask].dropna().mean()

        # Is vol still elevated at day 22? (> 1.1x pre-event)
        persistent = "YES" if vols_at_horizons.get(22, 0) > pre * 1.1 else "no"

        print(f"  {asset:<6} {pre:>9.1%} {vols_at_horizons.get(1, np.nan):>9.1%} "
              f"{vols_at_horizons.get(5, np.nan):>9.1%} {vols_at_horizons.get(10, np.nan):>9.1%} "
              f"{vols_at_horizons.get(22, np.nan):>9.1%} {persistent:>12}")

# ============================================================
# 8. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[8] SUMMARY & CONCLUSIONS")
print("=" * 70)

# Count significant findings
sig_count = 0
total_tests = 0
for event_name in all_results:
    for asset in all_results[event_name]:
        for h, r in all_results[event_name][asset].items():
            if not r.get('insufficient'):
                total_tests += 1
                if r['p_val'] < 0.05:
                    sig_count += 1

print(f"\n1. Total statistical tests: {total_tests}")
print(f"   Significant at p<0.05: {sig_count} ({sig_count/total_tests*100:.1f}%)" if total_tests > 0 else "   No tests")
print(f"   Expected by chance (5%): {total_tests * 0.05:.1f}")

# Strongest findings
print(f"\n2. Strongest findings (p < 0.05):")
for event_name in all_results:
    for asset in all_results[event_name]:
        for h, r in all_results[event_name][asset].items():
            if not r.get('insufficient') and r['p_val'] < 0.05:
                print(f"   - {event_name} → {asset} {h}d vol: "
                      f"ratio={r['vol_ratio']:.2f}x, t={r['t_stat']:.2f}, "
                      f"p={r['p_val']:.4f}, d={r['cohens_d']:.2f}")

# Climate trend conclusion
print(f"\n3. Long-term trend:")
for event_name, td in trend_data.items():
    if len(td) >= 3:
        freq_trend = td[-1]['freq'] - td[0]['freq']
        direction = "increasing" if freq_trend > 0 else "decreasing"
        print(f"   - {event_name}: frequency {direction} ({td[0]['freq']:.1f} → {td[-1]['freq']:.1f}/yr)")

# Overall assessment
print(f"\n4. Overall Assessment:")
print(f"   - Climate-proxy events CAN be identified from market data")
print(f"   - The question is whether they have INCREMENTAL vol impact")
print(f"     beyond what VIX already captures")

# FDR correction
if total_tests > 0 and sig_count > 0:
    print(f"\n5. Multiple Testing Correction (Benjamini-Hochberg):")
    all_pvals = []
    all_labels = []
    for event_name in all_results:
        for asset in all_results[event_name]:
            for h, r in all_results[event_name][asset].items():
                if not r.get('insufficient'):
                    all_pvals.append(r['p_val'])
                    all_labels.append(f"{event_name}→{asset}({h}d)")

    # BH correction
    sorted_idx = np.argsort(all_pvals)
    m = len(all_pvals)
    bh_threshold = [(i + 1) / m * 0.05 for i in range(m)]

    survive_count = 0
    for rank, idx in enumerate(sorted_idx):
        if all_pvals[idx] <= bh_threshold[rank]:
            survive_count += 1

    print(f"   - {m} tests total")
    print(f"   - {sig_count} nominally significant (p<0.05)")
    print(f"   - {survive_count} survive BH correction (q=0.05)")

    # List survivors
    if survive_count > 0:
        print(f"   Surviving findings:")
        for rank, idx in enumerate(sorted_idx[:survive_count]):
            if all_pvals[idx] <= bh_threshold[rank]:
                print(f"     - {all_labels[idx]}: p={all_pvals[idx]:.6f}")

# Save results
results_output = {
    'experiment': 'K117',
    'title': 'Climate/Weather Event Impact on Volatility',
    'data_range': f"{returns.index[0].date()} to {returns.index[-1].date()}",
    'n_observations': len(returns),
    'events': {},
    'significant_findings': [],
    'trend_data': {},
    'conclusion': '',
}

for event_name, event_mask in event_types.items():
    results_output['events'][event_name] = {
        'count': int(event_mask.sum()),
        'frequency_per_year': float(event_mask.sum() / ((returns.index[-1] - returns.index[0]).days / 365.25)),
    }

for event_name in all_results:
    for asset in all_results[event_name]:
        for h, r in all_results[event_name][asset].items():
            if not r.get('insufficient') and r['p_val'] < 0.05:
                results_output['significant_findings'].append({
                    'event': event_name,
                    'asset': asset,
                    'horizon': h,
                    'vol_ratio': round(r['vol_ratio'], 3),
                    't_stat': round(r['t_stat'], 3),
                    'p_value': round(r['p_val'], 6),
                    'cohens_d': round(r['cohens_d'], 3),
                })

for event_name, td in trend_data.items():
    results_output['trend_data'][event_name] = td

# Determine conclusion
if sig_count == 0:
    results_output['conclusion'] = "NULL RESULT: No significant climate event impact on volatility detected after controlling for market conditions."
elif survive_count == 0:
    results_output['conclusion'] = "WEAK: Some nominal significance but none survive multiple testing correction."
else:
    results_output['conclusion'] = f"POSITIVE: {survive_count} findings survive BH correction. Climate-proxy events have measurable vol impact."

print(f"\n{'='*70}")
print(f"CONCLUSION: {results_output['conclusion']}")
print(f"{'='*70}")

# Save JSON
output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/climate_event_vol/climate_event_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
