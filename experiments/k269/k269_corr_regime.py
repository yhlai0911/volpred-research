#!/usr/bin/env python3
"""
K269: SPY-GLD Correlation Regime — When Does the Diversification Benefit Break?
================================================================================
Background: K232 showed SPY-GLD R²=0.003 (nearly zero). But is this STABLE?
If correlation spikes during crises (when you need diversification most),
50/50 fails precisely when you need it.

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.

Methodology:
1. Rolling SPY-GLD correlation (22d, 66d, 252d windows)
2. Regime analysis by VIX level
3. Structural break detection (Bai-Perron style via sequential Chow tests)
4. Crisis deep-dives (GFC, COVID, 2022 rate hikes)
5. Conditional 50/50 performance in high-corr vs low-corr regimes

[提出: 用戶, 執行: Claude]
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
print("K269: SPY-GLD Correlation Regime Analysis")
print("=" * 70)

print("\n[1] Downloading SPY, GLD, VIX daily data 2005-2024...")
tickers = ['SPY', 'GLD', '^VIX']
data = {}
for ticker in tickers:
    df = yf.download(ticker, start='2004-11-01', end='2024-12-31',
                     progress=False, auto_adjust=True)
    close = df['Close']
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    data[ticker.replace('^', '')] = close
    print(f"  {ticker}: {len(close)} obs, {close.index[0].date()} to {close.index[-1].date()}")

# Align all series
prices = pd.DataFrame(data).dropna()
print(f"\n  Aligned dataset: {len(prices)} obs, {prices.index[0].date()} to {prices.index[-1].date()}")

# Returns
ret = prices[['SPY', 'GLD']].pct_change().dropna()
vix = prices['VIX'].reindex(ret.index)

print(f"  Returns: {len(ret)} obs")
print(f"  SPY mean daily ret: {ret['SPY'].mean()*252:.4f} (annualized)")
print(f"  GLD mean daily ret: {ret['GLD'].mean()*252:.4f} (annualized)")

# Full-sample correlation
full_corr = ret['SPY'].corr(ret['GLD'])
print(f"\n  Full-sample SPY-GLD correlation: {full_corr:.4f}")

results = {
    'experiment': 'K269',
    'title': 'SPY-GLD Correlation Regime Analysis',
    'data_source': 'yfinance',
    'period': f"{ret.index[0].date()} to {ret.index[-1].date()}",
    'n_obs': len(ret),
    'full_sample_correlation': round(full_corr, 4),
}

# ============================================================
# 2. Rolling Correlation Analysis
# ============================================================
print("\n" + "=" * 70)
print("[2] Rolling Correlation (22d, 66d, 252d)")
print("=" * 70)

windows = {'22d': 22, '66d': 66, '252d': 252}
rolling_corr = {}

for label, w in windows.items():
    rc = ret['SPY'].rolling(w).corr(ret['GLD'])
    rc = rc.dropna()
    rolling_corr[label] = rc

    pct_negative = (rc < 0).mean() * 100
    pct_positive = (rc > 0).mean() * 100
    pct_above_03 = (rc > 0.3).mean() * 100
    pct_below_neg03 = (rc < -0.3).mean() * 100

    print(f"\n  {label} rolling correlation:")
    print(f"    Mean:   {rc.mean():.4f}")
    print(f"    Std:    {rc.std():.4f}")
    print(f"    Min:    {rc.min():.4f}")
    print(f"    Max:    {rc.max():.4f}")
    print(f"    Median: {rc.median():.4f}")
    print(f"    % Negative: {pct_negative:.1f}%")
    print(f"    % Positive: {pct_positive:.1f}%")
    print(f"    % > 0.3:    {pct_above_03:.1f}%")
    print(f"    % < -0.3:   {pct_below_neg03:.1f}%")

    results[f'rolling_{label}'] = {
        'mean': round(rc.mean(), 4),
        'std': round(rc.std(), 4),
        'min': round(rc.min(), 4),
        'max': round(rc.max(), 4),
        'median': round(rc.median(), 4),
        'pct_negative': round(pct_negative, 1),
        'pct_positive': round(pct_positive, 1),
        'pct_above_0.3': round(pct_above_03, 1),
        'pct_below_-0.3': round(pct_below_neg03, 1),
    }

# ============================================================
# 3. VIX Regime Analysis
# ============================================================
print("\n" + "=" * 70)
print("[3] Correlation by VIX Regime")
print("=" * 70)

vix_aligned = vix.reindex(ret.index).dropna()
ret_aligned = ret.reindex(vix_aligned.index)

vix_bins = [(0, 15, 'VIX < 15 (calm)'),
            (15, 25, 'VIX 15-25 (normal)'),
            (25, 35, 'VIX 25-35 (elevated)'),
            (35, 999, 'VIX > 35 (crisis)')]

results['vix_regime_correlation'] = {}

for lo, hi, label in vix_bins:
    mask = (vix_aligned >= lo) & (vix_aligned < hi)
    n = mask.sum()
    if n < 30:
        print(f"\n  {label}: only {n} obs, skipping")
        continue

    sub_ret = ret_aligned[mask]
    corr_val = sub_ret['SPY'].corr(sub_ret['GLD'])

    # Bootstrap CI
    boot_corrs = []
    for _ in range(5000):
        idx = np.random.choice(len(sub_ret), size=len(sub_ret), replace=True)
        boot_sub = sub_ret.iloc[idx]
        boot_corrs.append(boot_sub['SPY'].corr(boot_sub['GLD']))
    boot_corrs = np.array(boot_corrs)
    ci_lo, ci_hi = np.percentile(boot_corrs, [2.5, 97.5])

    # Also compute using 66d rolling corr in this regime
    rc66_in_regime = rolling_corr['66d'].reindex(vix_aligned.index)[mask].dropna()

    print(f"\n  {label} (n={n}):")
    print(f"    Correlation:     {corr_val:.4f}  [{ci_lo:.4f}, {ci_hi:.4f}] 95% CI")
    print(f"    Mean 66d roll:   {rc66_in_regime.mean():.4f}" if len(rc66_in_regime) > 0 else "    (no rolling data)")

    results['vix_regime_correlation'][label] = {
        'n': int(n),
        'correlation': round(corr_val, 4),
        'ci_95': [round(ci_lo, 4), round(ci_hi, 4)],
        'mean_66d_rolling': round(rc66_in_regime.mean(), 4) if len(rc66_in_regime) > 0 else None,
    }

# Test: is correlation significantly different across regimes?
print("\n  --- Statistical Test: Correlation Difference Across Regimes ---")
# Compare calm (VIX<15) vs crisis (VIX>35) using Fisher z-transform
regime_pairs = [('VIX < 15 (calm)', 'VIX 25-35 (elevated)'),
                ('VIX < 15 (calm)', 'VIX > 35 (crisis)')]

for r1_label, r2_label in regime_pairs:
    if r1_label in results['vix_regime_correlation'] and r2_label in results['vix_regime_correlation']:
        r1 = results['vix_regime_correlation'][r1_label]
        r2 = results['vix_regime_correlation'][r2_label]
        # Fisher z-transform test
        z1 = np.arctanh(r1['correlation'])
        z2 = np.arctanh(r2['correlation'])
        se = np.sqrt(1/(r1['n']-3) + 1/(r2['n']-3))
        z_stat = (z1 - z2) / se
        p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
        print(f"\n  {r1_label} vs {r2_label}:")
        print(f"    r1={r1['correlation']:.4f} (n={r1['n']}), r2={r2['correlation']:.4f} (n={r2['n']})")
        print(f"    Fisher z-test: z={z_stat:.3f}, p={p_val:.4f} {'***' if p_val<0.01 else '**' if p_val<0.05 else '*' if p_val<0.1 else 'ns'}")

# ============================================================
# 4. Structural Break Detection
# ============================================================
print("\n" + "=" * 70)
print("[4] Structural Break Detection (Sequential Chow Tests)")
print("=" * 70)

# Use 252d rolling correlation for break detection
rc252 = rolling_corr['252d']

def find_breaks_sequential(series, min_segment=126, alpha=0.001, max_breaks=5):
    """
    Find structural breaks by sequential F-tests on the mean of a series.
    At each step, find the most significant break point in the largest segment,
    if the F-stat exceeds critical value.
    """
    breaks = []
    segments = [(0, len(series))]

    for _ in range(max_breaks):
        best_f = -1
        best_pos = -1
        best_seg_idx = -1

        for seg_idx, (start, end) in enumerate(segments):
            if end - start < 2 * min_segment:
                continue
            seg_data = series.values[start:end]

            # Try each possible break point
            for bp in range(min_segment, len(seg_data) - min_segment):
                left = seg_data[:bp]
                right = seg_data[bp:]
                n1, n2 = len(left), len(right)

                # F-test for difference in means
                grand_mean = seg_data.mean()
                ssr = np.sum((left - left.mean())**2) + np.sum((right - right.mean())**2)
                ssf = np.sum((seg_data - grand_mean)**2)

                if ssr == 0:
                    continue

                f_stat = ((ssf - ssr) / 1) / (ssr / (n1 + n2 - 2))

                if f_stat > best_f:
                    best_f = f_stat
                    best_pos = start + bp
                    best_seg_idx = seg_idx

        # Check significance
        if best_f < 0:
            break

        total_n = segments[best_seg_idx][1] - segments[best_seg_idx][0]
        p_val = 1 - stats.f.cdf(best_f, 1, total_n - 2)

        if p_val > alpha:
            break

        breaks.append((best_pos, best_f, p_val))

        # Split segment
        old_start, old_end = segments[best_seg_idx]
        segments[best_seg_idx] = (old_start, best_pos)
        segments.insert(best_seg_idx + 1, (best_pos, old_end))

    return breaks, segments

breaks, segments = find_breaks_sequential(rc252, min_segment=126, alpha=0.001)

results['structural_breaks'] = []
print(f"\n  Found {len(breaks)} structural breaks:")
for i, (pos, f_stat, p_val) in enumerate(sorted(breaks)):
    break_date = rc252.index[pos]
    corr_at_break = rc252.iloc[pos]
    print(f"    Break {i+1}: {break_date.date()} (corr={corr_at_break:.4f}, F={f_stat:.1f}, p={p_val:.2e})")
    results['structural_breaks'].append({
        'date': str(break_date.date()),
        'correlation_at_break': round(corr_at_break, 4),
        'f_stat': round(f_stat, 1),
        'p_value': f"{p_val:.2e}",
    })

# Regime means between breaks
print("\n  Correlation regimes between breaks:")
break_positions = sorted([pos for pos, _, _ in breaks])
all_boundaries = [0] + break_positions + [len(rc252)]
results['regime_means'] = []

for i in range(len(all_boundaries) - 1):
    start, end = all_boundaries[i], all_boundaries[i+1]
    segment = rc252.iloc[start:end]
    start_date = segment.index[0].date()
    end_date = segment.index[-1].date()
    print(f"    {start_date} to {end_date}: mean={segment.mean():.4f}, std={segment.std():.4f} (n={len(segment)})")
    results['regime_means'].append({
        'start': str(start_date),
        'end': str(end_date),
        'mean_corr': round(segment.mean(), 4),
        'std_corr': round(segment.std(), 4),
        'n': len(segment),
    })

# ============================================================
# 5. Crisis Deep-Dives
# ============================================================
print("\n" + "=" * 70)
print("[5] Crisis Deep-Dives")
print("=" * 70)

crisis_periods = {
    'GFC (2008-09 to 2009-03)': ('2008-09-01', '2009-03-31'),
    'Euro Crisis (2011-07 to 2011-12)': ('2011-07-01', '2011-12-31'),
    'COVID Crash (2020-02 to 2020-04)': ('2020-02-15', '2020-04-30'),
    'COVID March Liquidity (2020-03)': ('2020-03-01', '2020-03-31'),
    '2022 Rate Hikes (2022-01 to 2022-10)': ('2022-01-01', '2022-10-31'),
    '2022 Q3 (worst)': ('2022-07-01', '2022-09-30'),
}

results['crisis_analysis'] = {}

for crisis_name, (start, end) in crisis_periods.items():
    mask = (ret.index >= start) & (ret.index <= end)
    crisis_ret = ret[mask]
    crisis_vix = vix.reindex(crisis_ret.index)

    if len(crisis_ret) < 10:
        print(f"\n  {crisis_name}: insufficient data ({len(crisis_ret)} obs)")
        continue

    corr_val = crisis_ret['SPY'].corr(crisis_ret['GLD'])

    # SPY and GLD performance
    spy_cum = (1 + crisis_ret['SPY']).prod() - 1
    gld_cum = (1 + crisis_ret['GLD']).prod() - 1
    fifty_fifty_ret = 0.5 * crisis_ret['SPY'] + 0.5 * crisis_ret['GLD']
    ff_cum = (1 + fifty_fifty_ret).prod() - 1

    # SPY max drawdown in this period
    spy_prices_crisis = prices['SPY'].reindex(crisis_ret.index)
    spy_dd = (spy_prices_crisis / spy_prices_crisis.cummax() - 1).min()

    # 50/50 max drawdown
    ff_eq = (1 + fifty_fifty_ret).cumprod()
    ff_dd = (ff_eq / ff_eq.cummax() - 1).min()

    # Mean VIX
    mean_vix = crisis_vix.mean()

    # Days where both SPY and GLD fell
    both_down = ((crisis_ret['SPY'] < 0) & (crisis_ret['GLD'] < 0)).sum()
    pct_both_down = both_down / len(crisis_ret) * 100

    print(f"\n  {crisis_name} (n={len(crisis_ret)}):")
    print(f"    SPY-GLD correlation:  {corr_val:.4f}")
    print(f"    SPY cumulative:       {spy_cum*100:.1f}%")
    print(f"    GLD cumulative:       {gld_cum*100:.1f}%")
    print(f"    50/50 cumulative:     {ff_cum*100:.1f}%")
    print(f"    SPY max drawdown:     {spy_dd*100:.1f}%")
    print(f"    50/50 max drawdown:   {ff_dd*100:.1f}%")
    print(f"    Mean VIX:             {mean_vix:.1f}")
    print(f"    Days both down:       {both_down}/{len(crisis_ret)} ({pct_both_down:.0f}%)")

    results['crisis_analysis'][crisis_name] = {
        'n': len(crisis_ret),
        'correlation': round(corr_val, 4),
        'spy_cumulative': round(spy_cum * 100, 1),
        'gld_cumulative': round(gld_cum * 100, 1),
        'fifty_fifty_cumulative': round(ff_cum * 100, 1),
        'spy_max_drawdown': round(spy_dd * 100, 1),
        'fifty_fifty_max_drawdown': round(ff_dd * 100, 1),
        'mean_vix': round(mean_vix, 1),
        'days_both_down': int(both_down),
        'pct_both_down': round(pct_both_down, 1),
    }

# ============================================================
# 6. Conditional 50/50 Performance
# ============================================================
print("\n" + "=" * 70)
print("[6] Conditional 50/50 Performance: High-Corr vs Low-Corr Regimes")
print("=" * 70)

# Use 66d rolling correlation to define regimes
rc66 = rolling_corr['66d'].reindex(ret.index)
valid_mask = rc66.notna()
rc66_valid = rc66[valid_mask]
ret_valid = ret[valid_mask]

# Define regimes
corr_thresholds = {
    'Very negative (< -0.3)': (-999, -0.3),
    'Negative (-0.3 to 0)': (-0.3, 0),
    'Low positive (0 to 0.2)': (0, 0.2),
    'Moderate positive (0.2 to 0.4)': (0.2, 0.4),
    'High positive (> 0.4)': (0.4, 999),
}

results['conditional_performance'] = {}

print(f"\n  50/50 portfolio performance by correlation regime (66d rolling):")
print(f"  {'Regime':<35} {'N':>6} {'Ann Ret':>9} {'Ann Vol':>9} {'Sharpe':>8} {'MDD':>8}")
print(f"  {'-'*35} {'-'*6} {'-'*9} {'-'*9} {'-'*8} {'-'*8}")

for regime_name, (lo, hi) in corr_thresholds.items():
    mask = (rc66_valid >= lo) & (rc66_valid < hi)
    n = mask.sum()
    if n < 30:
        print(f"  {regime_name:<35} {n:>6} (insufficient)")
        continue

    sub_ret = ret_valid[mask]
    ff_ret = 0.5 * sub_ret['SPY'] + 0.5 * sub_ret['GLD']
    spy_ret_sub = sub_ret['SPY']

    # Annualized metrics (approximate—these are non-contiguous days)
    ann_ret_ff = ff_ret.mean() * 252
    ann_vol_ff = ff_ret.std() * np.sqrt(252)
    sharpe_ff = ann_ret_ff / ann_vol_ff if ann_vol_ff > 0 else 0

    ann_ret_spy = spy_ret_sub.mean() * 252
    ann_vol_spy = spy_ret_sub.std() * np.sqrt(252)
    sharpe_spy = ann_ret_spy / ann_vol_spy if ann_vol_spy > 0 else 0

    # MDD for the 50/50 in this regime (non-contiguous, but informative)
    ff_eq = (1 + ff_ret).cumprod()
    ff_dd = (ff_eq / ff_eq.cummax() - 1).min()

    print(f"  {regime_name:<35} {n:>6} {ann_ret_ff*100:>8.1f}% {ann_vol_ff*100:>8.1f}% {sharpe_ff:>8.2f} {ff_dd*100:>7.1f}%")

    results['conditional_performance'][regime_name] = {
        'n': int(n),
        'ann_return_5050': round(ann_ret_ff * 100, 2),
        'ann_vol_5050': round(ann_vol_ff * 100, 2),
        'sharpe_5050': round(sharpe_ff, 3),
        'max_drawdown_5050': round(ff_dd * 100, 1),
        'ann_return_spy': round(ann_ret_spy * 100, 2),
        'sharpe_spy': round(sharpe_spy, 3),
    }

# ============================================================
# 7. Year-by-Year Correlation
# ============================================================
print("\n" + "=" * 70)
print("[7] Year-by-Year SPY-GLD Correlation")
print("=" * 70)

results['yearly_correlation'] = {}
print(f"\n  {'Year':<6} {'Corr':>8} {'SPY Ret':>9} {'GLD Ret':>9} {'50/50 Ret':>10} {'50/50 Vol':>10} {'VIX Avg':>8}")
print(f"  {'-'*6} {'-'*8} {'-'*9} {'-'*9} {'-'*10} {'-'*10} {'-'*8}")

for year in range(2005, 2025):
    mask = ret.index.year == year
    if mask.sum() < 50:
        continue
    yr_ret = ret[mask]
    yr_vix = vix.reindex(yr_ret.index)

    corr_yr = yr_ret['SPY'].corr(yr_ret['GLD'])
    spy_ann = yr_ret['SPY'].mean() * 252
    gld_ann = yr_ret['GLD'].mean() * 252
    ff = 0.5 * yr_ret['SPY'] + 0.5 * yr_ret['GLD']
    ff_ann = ff.mean() * 252
    ff_vol = ff.std() * np.sqrt(252)
    vix_avg = yr_vix.mean()

    print(f"  {year:<6} {corr_yr:>8.4f} {spy_ann*100:>8.1f}% {gld_ann*100:>8.1f}% {ff_ann*100:>9.1f}% {ff_vol*100:>9.1f}% {vix_avg:>8.1f}")

    results['yearly_correlation'][str(year)] = {
        'correlation': round(corr_yr, 4),
        'spy_return': round(spy_ann * 100, 1),
        'gld_return': round(gld_ann * 100, 1),
        'ff_return': round(ff_ann * 100, 1),
        'ff_vol': round(ff_vol * 100, 1),
        'vix_avg': round(vix_avg, 1),
    }

# ============================================================
# 8. Key Question: Does Correlation Rise in Crises?
# ============================================================
print("\n" + "=" * 70)
print("[8] KEY QUESTION: Does SPY-GLD Correlation Rise When VIX Spikes?")
print("=" * 70)

# Regression: 66d rolling corr on VIX level
rc66_for_reg = rolling_corr['66d'].reindex(vix.index).dropna()
vix_for_reg = vix.reindex(rc66_for_reg.index).dropna()
common_idx = rc66_for_reg.index.intersection(vix_for_reg.index)
rc66_reg = rc66_for_reg.loc[common_idx]
vix_reg = vix_for_reg.loc[common_idx]

slope, intercept, r_value, p_value, std_err = stats.linregress(vix_reg, rc66_reg)
print(f"\n  OLS: 66d_rolling_corr = {intercept:.4f} + {slope:.4f} * VIX")
print(f"  R²={r_value**2:.4f}, t={slope/std_err:.2f}, p={p_value:.2e}")
print(f"  Interpretation: For VIX +10, correlation changes by {slope*10:.4f}")

results['vix_corr_regression'] = {
    'intercept': round(intercept, 4),
    'slope': round(slope, 6),
    'r_squared': round(r_value**2, 4),
    't_stat': round(slope/std_err, 2),
    'p_value': f"{p_value:.2e}",
    'slope_per_10_vix': round(slope * 10, 4),
}

# Rank correlation (Spearman) — more robust
spearman_r, spearman_p = stats.spearmanr(vix_reg, rc66_reg)
print(f"\n  Spearman rank correlation: r={spearman_r:.4f}, p={spearman_p:.2e}")
results['vix_corr_spearman'] = {
    'rho': round(spearman_r, 4),
    'p_value': f"{spearman_p:.2e}",
}

# Extreme VIX days analysis
print("\n  --- Extreme VIX Days (top 1%) ---")
vix_p99 = vix.quantile(0.99)
extreme_days = vix[vix >= vix_p99].index
extreme_ret = ret.reindex(extreme_days).dropna()
if len(extreme_ret) >= 10:
    extreme_corr = extreme_ret['SPY'].corr(extreme_ret['GLD'])
    both_down_extreme = ((extreme_ret['SPY'] < 0) & (extreme_ret['GLD'] < 0)).mean() * 100
    print(f"  VIX >= {vix_p99:.1f}: {len(extreme_ret)} days")
    print(f"  Correlation on extreme VIX days: {extreme_corr:.4f}")
    print(f"  % both SPY & GLD down: {both_down_extreme:.0f}%")
    print(f"  Mean SPY return: {extreme_ret['SPY'].mean()*100:.2f}%")
    print(f"  Mean GLD return: {extreme_ret['GLD'].mean()*100:.2f}%")

    results['extreme_vix_days'] = {
        'vix_threshold': round(vix_p99, 1),
        'n_days': len(extreme_ret),
        'correlation': round(extreme_corr, 4),
        'pct_both_down': round(both_down_extreme, 1),
        'mean_spy_return': round(extreme_ret['SPY'].mean()*100, 2),
        'mean_gld_return': round(extreme_ret['GLD'].mean()*100, 2),
    }

# ============================================================
# 9. Diversification Benefit Stability Score
# ============================================================
print("\n" + "=" * 70)
print("[9] Diversification Benefit Stability Assessment")
print("=" * 70)

# Compute: what fraction of the time does GLD actually hedge SPY?
# (i.e., GLD up when SPY down)
spy_down = ret['SPY'] < 0
gld_up_when_spy_down = (ret['GLD'][spy_down] > 0).mean() * 100
gld_mean_when_spy_down = ret['GLD'][spy_down].mean() * 100

print(f"\n  When SPY is down ({spy_down.sum()} days):")
print(f"    GLD is up: {gld_up_when_spy_down:.1f}% of the time")
print(f"    Mean GLD return: {gld_mean_when_spy_down:.3f}%")

# Worst SPY days (bottom 5%)
spy_worst_5pct = ret['SPY'] <= ret['SPY'].quantile(0.05)
gld_on_worst_spy = ret['GLD'][spy_worst_5pct]
print(f"\n  On SPY's worst 5% days ({spy_worst_5pct.sum()} days):")
print(f"    Mean SPY return: {ret['SPY'][spy_worst_5pct].mean()*100:.2f}%")
print(f"    Mean GLD return: {gld_on_worst_spy.mean()*100:.2f}%")
print(f"    GLD positive: {(gld_on_worst_spy > 0).mean()*100:.0f}%")
print(f"    Correlation on these days: {ret['SPY'][spy_worst_5pct].corr(gld_on_worst_spy):.4f}")

# Worst SPY days (bottom 1%)
spy_worst_1pct = ret['SPY'] <= ret['SPY'].quantile(0.01)
gld_on_worst_spy_1 = ret['GLD'][spy_worst_1pct]
print(f"\n  On SPY's worst 1% days ({spy_worst_1pct.sum()} days):")
print(f"    Mean SPY return: {ret['SPY'][spy_worst_1pct].mean()*100:.2f}%")
print(f"    Mean GLD return: {gld_on_worst_spy_1.mean()*100:.2f}%")
print(f"    GLD positive: {(gld_on_worst_spy_1 > 0).mean()*100:.0f}%")

results['hedge_effectiveness'] = {
    'gld_up_when_spy_down_pct': round(gld_up_when_spy_down, 1),
    'gld_mean_return_when_spy_down': round(gld_mean_when_spy_down, 3),
    'worst_5pct_spy': {
        'n': int(spy_worst_5pct.sum()),
        'mean_spy_ret': round(ret['SPY'][spy_worst_5pct].mean()*100, 2),
        'mean_gld_ret': round(gld_on_worst_spy.mean()*100, 2),
        'gld_positive_pct': round((gld_on_worst_spy > 0).mean()*100, 0),
    },
    'worst_1pct_spy': {
        'n': int(spy_worst_1pct.sum()),
        'mean_spy_ret': round(ret['SPY'][spy_worst_1pct].mean()*100, 2),
        'mean_gld_ret': round(gld_on_worst_spy_1.mean()*100, 2),
        'gld_positive_pct': round((gld_on_worst_spy_1 > 0).mean()*100, 0),
    },
}

# ============================================================
# 10. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("[10] SUMMARY & CONCLUSIONS")
print("=" * 70)

print(f"""
  Full-sample SPY-GLD correlation: {full_corr:.4f}

  KEY FINDINGS:

  1. ROLLING CORRELATION IS HIGHLY UNSTABLE:
     - 66d rolling corr ranges from {results['rolling_66d']['min']:.2f} to {results['rolling_66d']['max']:.2f}
     - Std dev: {results['rolling_66d']['std']:.2f} (vs mean {results['rolling_66d']['mean']:.2f})
     - Negative {results['rolling_66d']['pct_negative']:.0f}% of the time

  2. VIX-CORRELATION RELATIONSHIP:
     - Slope: {slope:.4f} per VIX point (R²={r_value**2:.4f})
     - Spearman rho: {spearman_r:.4f}

  3. CRISIS BEHAVIOR:
""")

for crisis_name, crisis_data in results['crisis_analysis'].items():
    print(f"     {crisis_name}: corr={crisis_data['correlation']:.2f}, "
          f"SPY={crisis_data['spy_cumulative']:+.0f}%, GLD={crisis_data['gld_cumulative']:+.0f}%, "
          f"50/50={crisis_data['fifty_fifty_cumulative']:+.0f}%")

print(f"""
  4. HEDGE EFFECTIVENESS:
     - GLD up when SPY down: {gld_up_when_spy_down:.0f}%
     - On SPY's worst 1% days: GLD averages {gld_on_worst_spy_1.mean()*100:+.2f}%

  BOTTOM LINE:
  The near-zero average correlation MASKS large time-variation.
  The critical question is whether correlation INCREASES (bad) or
  DECREASES (good) during crises — which determines if 50/50 works
  when you need it most.
""")

# ============================================================
# Save results
# ============================================================
output_path = 'experiments/k269_corr_regime_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {output_path}")
print("\n" + "=" * 70)
print("K269 COMPLETE")
print("=" * 70)
