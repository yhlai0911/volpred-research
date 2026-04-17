"""
K364: Monday Effect Deep Dive — Is There a Tradeable Day-of-Week Pattern?
=========================================================================
跳躍式探索：經典 Monday effect 是否仍存在？是否可交易？

Pre-experiment context:
- K215 tested DOW on |returns| (vol proxy) → NS for equity
- K283 found rebalance day doesn't matter
- This tests DIRECTIONAL returns (the classic Monday effect)

Data: SPY, GLD daily from yfinance, 2005-2024
Methodology:
1. Mean return by day of week + t-test for Monday < 0
2. Decade-by-decade breakdown (has it disappeared?)
3. Friday-Monday correlation + weekend gap analysis
4. VIX day-of-week pattern
5. Cross-asset comparison (SPY vs GLD)
6. Strategy simulation: 100% cash on Friday close → buy Monday close

[提出: Claude (autonomous research), 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K364: Monday Effect Deep Dive")
print("=" * 70)

assets = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    '^VIX': '^VIX'
}

data = {}
for name, ticker in assets.items():
    df = yf.download(ticker, start='2005-01-01', end='2025-01-01', auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"{name}: {len(df)} days, {df.index[0].date()} to {df.index[-1].date()}")

# Calculate returns
for name in ['SPY', 'GLD']:
    data[name]['Return'] = data[name]['Close'].pct_change()
    data[name]['LogReturn'] = np.log(data[name]['Close'] / data[name]['Close'].shift(1))
    data[name]['DOW'] = data[name].index.dayofweek  # 0=Mon, 4=Fri
    data[name]['DOW_name'] = data[name].index.day_name()

# VIX
data['^VIX']['DOW'] = data['^VIX'].index.dayofweek
data['^VIX']['DOW_name'] = data['^VIX'].index.day_name()

print(f"\nSPY returns: {data['SPY']['Return'].dropna().shape[0]} observations")
print(f"GLD returns: {data['GLD']['Return'].dropna().shape[0]} observations")

results = {}

# ============================================================
# 2. Mean Return by Day of Week
# ============================================================
print("\n" + "=" * 70)
print("SECTION 1: Mean Return by Day of Week")
print("=" * 70)

dow_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return'])

    print(f"\n--- {asset_name} (2005-2024) ---")
    print(f"{'Day':<12} {'Mean(%)':<10} {'Std(%)':<10} {'N':<8} {'t-stat':<10} {'p-value':<10} {'Sig?'}")
    print("-" * 72)

    asset_results = {}
    for dow in range(5):
        day_returns = df[df['DOW'] == dow]['Return'].values
        mean_ret = np.mean(day_returns) * 100
        std_ret = np.std(day_returns, ddof=1) * 100
        n = len(day_returns)

        # t-test: mean != 0
        t_stat, p_val = stats.ttest_1samp(day_returns, 0)
        sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""

        print(f"{dow_names[dow]:<12} {mean_ret:>8.4f}  {std_ret:>8.4f}  {n:<8d} {t_stat:>8.3f}  {p_val:>8.4f}  {sig}")

        asset_results[dow_names[dow]] = {
            'mean_pct': round(mean_ret, 6),
            'std_pct': round(std_ret, 4),
            'n': int(n),
            't_stat': round(t_stat, 4),
            'p_value': round(p_val, 6)
        }

    # Annualized returns by DOW (assuming 252 trading days, ~50 per DOW)
    print(f"\nAnnualized returns (approx 50 days per DOW):")
    for dow in range(5):
        day_returns = df[df['DOW'] == dow]['Return'].values
        ann_ret = np.mean(day_returns) * 252 * 100  # rough annualization
        print(f"  {dow_names[dow]:<12}: {ann_ret:>8.2f}% annual (if only traded that day)")

    # ANOVA: are DOW means significantly different?
    groups = [df[df['DOW'] == dow]['Return'].values for dow in range(5)]
    f_stat, f_pval = stats.f_oneway(*groups)
    print(f"\nANOVA F-test (all DOW equal?): F={f_stat:.4f}, p={f_pval:.4f}")

    # Kruskal-Wallis (non-parametric)
    h_stat, h_pval = stats.kruskal(*groups)
    print(f"Kruskal-Wallis test: H={h_stat:.4f}, p={h_pval:.4f}")

    asset_results['ANOVA_F'] = round(f_stat, 4)
    asset_results['ANOVA_p'] = round(f_pval, 6)
    asset_results['KW_H'] = round(h_stat, 4)
    asset_results['KW_p'] = round(h_pval, 6)

    results[f'{asset_name}_dow'] = asset_results

# ============================================================
# 3. Monday Effect: One-sided test (Monday < 0?)
# ============================================================
print("\n" + "=" * 70)
print("SECTION 2: Is Monday Return Significantly Negative?")
print("=" * 70)

for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return'])
    mon_returns = df[df['DOW'] == 0]['Return'].values

    # One-sided t-test: H0: mu >= 0, Ha: mu < 0
    t_stat, p_two = stats.ttest_1samp(mon_returns, 0)
    p_one = p_two / 2 if t_stat < 0 else 1 - p_two / 2

    print(f"\n{asset_name} Monday returns:")
    print(f"  Mean: {np.mean(mon_returns)*100:.4f}%")
    print(f"  Median: {np.median(mon_returns)*100:.4f}%")
    print(f"  N: {len(mon_returns)}")
    print(f"  t-stat: {t_stat:.4f}")
    print(f"  p-value (one-sided, Monday < 0): {p_one:.4f}")
    print(f"  Fraction negative: {np.mean(mon_returns < 0)*100:.1f}%")

    # Wilcoxon signed-rank (non-parametric)
    w_stat, w_pval = stats.wilcoxon(mon_returns, alternative='less')
    print(f"  Wilcoxon signed-rank (one-sided): W={w_stat:.0f}, p={w_pval:.4f}")

    results[f'{asset_name}_monday_onesided'] = {
        'mean_pct': round(np.mean(mon_returns) * 100, 6),
        'median_pct': round(np.median(mon_returns) * 100, 6),
        'n': int(len(mon_returns)),
        't_stat': round(t_stat, 4),
        'p_one_sided': round(p_one, 6),
        'frac_negative': round(np.mean(mon_returns < 0), 4),
        'wilcoxon_p': round(w_pval, 6)
    }

# ============================================================
# 4. Decade-by-Decade Breakdown
# ============================================================
print("\n" + "=" * 70)
print("SECTION 3: Monday Effect by Decade (Has It Disappeared?)")
print("=" * 70)

decades = {
    '2005-2009': ('2005-01-01', '2009-12-31'),
    '2010-2014': ('2010-01-01', '2014-12-31'),
    '2015-2019': ('2015-01-01', '2019-12-31'),
    '2020-2024': ('2020-01-01', '2024-12-31'),
}

for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return'])

    print(f"\n--- {asset_name} Monday Returns by Period ---")
    print(f"{'Period':<12} {'Mean(%)':<10} {'N':<6} {'t-stat':<10} {'p(Mon<0)':<10} {'%Neg':<8} {'Sig?'}")
    print("-" * 68)

    decade_results = {}
    for period_name, (start, end) in decades.items():
        mask = (df.index >= start) & (df.index <= end)
        mon_ret = df[mask & (df['DOW'] == 0)]['Return'].values

        if len(mon_ret) < 10:
            continue

        mean_r = np.mean(mon_ret) * 100
        t_stat, p_two = stats.ttest_1samp(mon_ret, 0)
        p_one = p_two / 2 if t_stat < 0 else 1 - p_two / 2
        frac_neg = np.mean(mon_ret < 0) * 100
        sig = "***" if p_one < 0.01 else "**" if p_one < 0.05 else "*" if p_one < 0.10 else ""

        print(f"{period_name:<12} {mean_r:>8.4f}  {len(mon_ret):<6d} {t_stat:>8.3f}  {p_one:>8.4f}  {frac_neg:>6.1f}%  {sig}")

        decade_results[period_name] = {
            'mean_pct': round(mean_r, 6),
            'n': int(len(mon_ret)),
            't_stat': round(t_stat, 4),
            'p_one_sided': round(p_one, 6),
            'frac_negative': round(frac_neg, 2)
        }

    results[f'{asset_name}_monday_by_decade'] = decade_results

# ============================================================
# 5. Friday-Monday Correlation + Weekend Gap
# ============================================================
print("\n" + "=" * 70)
print("SECTION 4: Friday-Monday Correlation + Weekend Gap")
print("=" * 70)

for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return']).copy()

    # Build Friday-Monday pairs
    fri_data = df[df['DOW'] == 4][['Return', 'Close']].copy()
    fri_data.columns = ['Fri_Return', 'Fri_Close']

    mon_data = df[df['DOW'] == 0][['Return', 'Close', 'Open']].copy()
    mon_data.columns = ['Mon_Return', 'Mon_Close', 'Mon_Open']

    # Match each Monday to the previous Friday
    pairs = []
    for mon_date in mon_data.index:
        # Find the most recent Friday before this Monday
        prev_fridays = fri_data.index[fri_data.index < mon_date]
        if len(prev_fridays) == 0:
            continue
        fri_date = prev_fridays[-1]
        # Only match if it's within 4 calendar days (normal weekend)
        if (mon_date - fri_date).days <= 4:
            pairs.append({
                'fri_date': fri_date,
                'mon_date': mon_date,
                'fri_return': fri_data.loc[fri_date, 'Fri_Return'],
                'fri_close': fri_data.loc[fri_date, 'Fri_Close'],
                'mon_return': mon_data.loc[mon_date, 'Mon_Return'],
                'mon_open': mon_data.loc[mon_date, 'Mon_Open'],
                'mon_close': mon_data.loc[mon_date, 'Mon_Close'],
            })

    pairs_df = pd.DataFrame(pairs)

    # Weekend gap = Monday open / Friday close - 1
    pairs_df['weekend_gap'] = pairs_df['mon_open'] / pairs_df['fri_close'] - 1
    # Intraday Monday = Monday close / Monday open - 1
    pairs_df['mon_intraday'] = pairs_df['mon_close'] / pairs_df['mon_open'] - 1

    print(f"\n--- {asset_name} Friday-Monday Analysis ({len(pairs_df)} pairs) ---")

    # Correlation
    corr, corr_p = stats.pearsonr(pairs_df['fri_return'], pairs_df['mon_return'])
    print(f"Correlation(Fri return, Mon return): r={corr:.4f}, p={corr_p:.4f}")

    # Spearman rank correlation
    rho, rho_p = stats.spearmanr(pairs_df['fri_return'], pairs_df['mon_return'])
    print(f"Spearman(Fri return, Mon return): rho={rho:.4f}, p={rho_p:.4f}")

    # Weekend gap statistics
    gap_mean = pairs_df['weekend_gap'].mean() * 100
    gap_std = pairs_df['weekend_gap'].std() * 100
    gap_t, gap_p = stats.ttest_1samp(pairs_df['weekend_gap'], 0)
    print(f"\nWeekend gap (Mon open / Fri close - 1):")
    print(f"  Mean: {gap_mean:.4f}%, Std: {gap_std:.4f}%")
    print(f"  t-stat: {gap_t:.4f}, p={gap_p:.4f}")
    print(f"  Mean abs gap: {pairs_df['weekend_gap'].abs().mean()*100:.4f}%")

    # Monday intraday
    intra_mean = pairs_df['mon_intraday'].mean() * 100
    intra_t, intra_p = stats.ttest_1samp(pairs_df['mon_intraday'], 0)
    print(f"\nMonday intraday (Close/Open - 1):")
    print(f"  Mean: {intra_mean:.4f}%, t={intra_t:.4f}, p={intra_p:.4f}")

    # Does Friday direction predict Monday?
    fri_up = pairs_df['fri_return'] > 0
    mon_after_fri_up = pairs_df[fri_up]['mon_return'].mean() * 100
    mon_after_fri_down = pairs_df[~fri_up]['mon_return'].mean() * 100

    print(f"\nMonday return conditional on Friday:")
    print(f"  After Friday UP:   {mon_after_fri_up:.4f}% (N={fri_up.sum()})")
    print(f"  After Friday DOWN: {mon_after_fri_down:.4f}% (N={(~fri_up).sum()})")

    # Two-sample t-test
    t_cond, p_cond = stats.ttest_ind(
        pairs_df[fri_up]['mon_return'].values,
        pairs_df[~fri_up]['mon_return'].values
    )
    print(f"  t-test (difference): t={t_cond:.4f}, p={p_cond:.4f}")

    results[f'{asset_name}_fri_mon'] = {
        'n_pairs': int(len(pairs_df)),
        'pearson_r': round(corr, 4),
        'pearson_p': round(corr_p, 6),
        'spearman_rho': round(rho, 4),
        'spearman_p': round(rho_p, 6),
        'weekend_gap_mean_pct': round(gap_mean, 6),
        'weekend_gap_std_pct': round(gap_std, 4),
        'weekend_gap_t': round(gap_t, 4),
        'weekend_gap_p': round(gap_p, 6),
        'mon_intraday_mean_pct': round(intra_mean, 6),
        'mon_intraday_t': round(intra_t, 4),
        'mon_intraday_p': round(intra_p, 6),
        'mon_after_fri_up_pct': round(mon_after_fri_up, 6),
        'mon_after_fri_down_pct': round(mon_after_fri_down, 6),
        'conditional_t': round(t_cond, 4),
        'conditional_p': round(p_cond, 6)
    }

# ============================================================
# 6. VIX Day-of-Week Pattern
# ============================================================
print("\n" + "=" * 70)
print("SECTION 5: VIX Day-of-Week Pattern")
print("=" * 70)

vix_df = data['^VIX'].copy()
vix_df['VIX_change'] = vix_df['Close'].pct_change()

print(f"\n--- VIX Level by Day of Week ---")
print(f"{'Day':<12} {'Mean VIX':<12} {'Median VIX':<12} {'N':<8}")
print("-" * 46)

vix_dow_results = {}
for dow in range(5):
    day_vix = vix_df[vix_df['DOW'] == dow]['Close'].dropna().values
    mean_v = np.mean(day_vix)
    med_v = np.median(day_vix)
    print(f"{dow_names[dow]:<12} {mean_v:>10.2f}  {med_v:>10.2f}  {len(day_vix):<8}")
    vix_dow_results[dow_names[dow]] = {
        'mean_vix': round(float(mean_v), 2),
        'median_vix': round(float(med_v), 2),
        'n': int(len(day_vix))
    }

print(f"\n--- VIX Daily Change by Day of Week ---")
print(f"{'Day':<12} {'Mean Chg(%)':<12} {'N':<8} {'t-stat':<10} {'p-value':<10}")
print("-" * 54)

for dow in range(5):
    day_chg = vix_df[vix_df['DOW'] == dow]['VIX_change'].dropna().values
    mean_chg = np.mean(day_chg) * 100
    t, p = stats.ttest_1samp(day_chg, 0)
    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
    print(f"{dow_names[dow]:<12} {mean_chg:>10.4f}  {len(day_chg):<8} {t:>8.3f}  {p:>8.4f}  {sig}")
    vix_dow_results[f'{dow_names[dow]}_change'] = {
        'mean_change_pct': round(mean_chg, 6),
        'n': int(len(day_chg)),
        't_stat': round(t, 4),
        'p_value': round(p, 6)
    }

# VIX ANOVA
vix_groups = [vix_df[vix_df['DOW'] == dow]['VIX_change'].dropna().values for dow in range(5)]
f_vix, fp_vix = stats.f_oneway(*[g for g in vix_groups if len(g) > 0])
print(f"\nANOVA (VIX change across DOW): F={f_vix:.4f}, p={fp_vix:.4f}")
vix_dow_results['ANOVA_F'] = round(f_vix, 4)
vix_dow_results['ANOVA_p'] = round(fp_vix, 6)

# VIX Friday close vs Monday open
vix_fri = vix_df[vix_df['DOW'] == 4][['Close']].copy()
vix_mon = vix_df[vix_df['DOW'] == 0][['Open', 'Close']].copy()

# Match Friday-Monday pairs
vix_pairs = []
for mon_date in vix_mon.index:
    prev_fri = vix_fri.index[vix_fri.index < mon_date]
    if len(prev_fri) > 0 and (mon_date - prev_fri[-1]).days <= 4:
        vix_pairs.append({
            'fri_close': vix_fri.loc[prev_fri[-1], 'Close'],
            'mon_open': vix_mon.loc[mon_date, 'Open'],
        })

vix_pairs_df = pd.DataFrame(vix_pairs)
vix_pairs_df['vix_weekend_change'] = vix_pairs_df['mon_open'] / vix_pairs_df['fri_close'] - 1

vix_wk_mean = vix_pairs_df['vix_weekend_change'].mean() * 100
vix_wk_t, vix_wk_p = stats.ttest_1samp(vix_pairs_df['vix_weekend_change'], 0)
print(f"\nVIX weekend change (Mon open / Fri close - 1):")
print(f"  Mean: {vix_wk_mean:.4f}%, t={vix_wk_t:.4f}, p={vix_wk_p:.4f}")
print(f"  N={len(vix_pairs_df)}")
print(f"  Fraction VIX increases over weekend: {(vix_pairs_df['vix_weekend_change'] > 0).mean()*100:.1f}%")

vix_dow_results['weekend_vix_change_pct'] = round(vix_wk_mean, 6)
vix_dow_results['weekend_vix_t'] = round(vix_wk_t, 4)
vix_dow_results['weekend_vix_p'] = round(vix_wk_p, 6)
vix_dow_results['frac_vix_up_weekend'] = round((vix_pairs_df['vix_weekend_change'] > 0).mean(), 4)

results['VIX_dow'] = vix_dow_results

# ============================================================
# 7. Strategy: Skip Monday (100% cash Fri close → Mon close)
# ============================================================
print("\n" + "=" * 70)
print("SECTION 6: Strategy — Skip Monday")
print("=" * 70)

for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return']).copy()

    # Buy & hold
    bh_returns = df['Return'].values
    bh_cum = np.cumprod(1 + bh_returns)
    bh_annual = (bh_cum[-1]) ** (252 / len(bh_returns)) - 1
    bh_vol = np.std(bh_returns) * np.sqrt(252)
    bh_sharpe = bh_annual / bh_vol if bh_vol > 0 else 0

    # Skip Monday (0 return on Mondays)
    skip_returns = df['Return'].copy()
    skip_returns[df['DOW'] == 0] = 0  # cash on Monday
    skip_cum = np.cumprod(1 + skip_returns.values)
    skip_annual = (skip_cum[-1]) ** (252 / len(skip_returns)) - 1
    skip_vol = np.std(skip_returns.values) * np.sqrt(252)
    skip_sharpe = skip_annual / skip_vol if skip_vol > 0 else 0

    # Only Monday (only hold on Mondays)
    only_mon_returns = df['Return'].copy()
    only_mon_returns[df['DOW'] != 0] = 0
    only_cum = np.cumprod(1 + only_mon_returns.values)
    only_annual = (only_cum[-1]) ** (252 / len(only_mon_returns)) - 1
    only_vol = np.std(only_mon_returns.values) * np.sqrt(252)
    only_sharpe = only_annual / only_vol if only_vol > 0 else 0

    # Maximum drawdown
    def max_drawdown(cum_returns):
        peak = np.maximum.accumulate(cum_returns)
        dd = cum_returns / peak - 1
        return np.min(dd)

    bh_mdd = max_drawdown(bh_cum)
    skip_mdd = max_drawdown(skip_cum)

    print(f"\n--- {asset_name} Strategy Comparison ---")
    print(f"{'Strategy':<20} {'Annual Ret':<14} {'Annual Vol':<14} {'Sharpe':<10} {'MDD':<10}")
    print("-" * 68)
    print(f"{'Buy & Hold':<20} {bh_annual*100:>10.2f}%   {bh_vol*100:>10.2f}%   {bh_sharpe:>8.3f}  {bh_mdd*100:>8.2f}%")
    print(f"{'Skip Monday':<20} {skip_annual*100:>10.2f}%   {skip_vol*100:>10.2f}%   {skip_sharpe:>8.3f}  {skip_mdd*100:>8.2f}%")
    print(f"{'Only Monday':<20} {only_annual*100:>10.2f}%   {only_vol*100:>10.2f}%   {only_sharpe:>8.3f}  {'N/A':>8}")

    # Statistical comparison: Skip Monday vs BnH
    # Paired t-test on daily returns difference
    diff = skip_returns.values - bh_returns
    diff_t, diff_p = stats.ttest_1samp(diff, 0)
    print(f"\nSkip-Monday vs BnH: t={diff_t:.4f}, p={diff_p:.4f}")

    # Transaction cost analysis
    # Skip Monday means 2 trades per week (sell Fri close, buy Mon close)
    # Assume 5 bps round trip
    n_weeks = len(pairs_df)  # approximate
    tc_annual = n_weeks / (len(df) / 252) * 0.0005 * 100  # approximate annual TC
    net_excess = (skip_annual - bh_annual) * 100 - tc_annual
    print(f"Approximate annual transaction cost (@5bps RT): {tc_annual:.2f}%")
    print(f"Net excess after TC: {net_excess:.2f}%")

    results[f'{asset_name}_strategy'] = {
        'bh_annual_ret': round(bh_annual * 100, 4),
        'bh_annual_vol': round(bh_vol * 100, 4),
        'bh_sharpe': round(bh_sharpe, 4),
        'bh_mdd': round(bh_mdd * 100, 4),
        'skip_mon_annual_ret': round(skip_annual * 100, 4),
        'skip_mon_annual_vol': round(skip_vol * 100, 4),
        'skip_mon_sharpe': round(skip_sharpe, 4),
        'skip_mon_mdd': round(skip_mdd * 100, 4),
        'only_mon_annual_ret': round(only_annual * 100, 4),
        'skip_vs_bh_t': round(diff_t, 4),
        'skip_vs_bh_p': round(diff_p, 6),
        'est_annual_tc_pct': round(tc_annual, 4),
        'net_excess_after_tc': round(net_excess, 4)
    }

# ============================================================
# 8. Best/Worst Day Strategy
# ============================================================
print("\n" + "=" * 70)
print("SECTION 7: All Day-of-Week Strategies (SPY)")
print("=" * 70)

df_spy = data['SPY'].dropna(subset=['Return']).copy()

print(f"\n{'Skip Day':<14} {'Ann Ret':<12} {'Ann Vol':<12} {'Sharpe':<10}")
print("-" * 50)

for skip_dow in range(5):
    skip_ret = df_spy['Return'].copy()
    skip_ret[df_spy['DOW'] == skip_dow] = 0
    cum = np.cumprod(1 + skip_ret.values)
    ann_r = cum[-1] ** (252 / len(skip_ret)) - 1
    ann_v = np.std(skip_ret.values) * np.sqrt(252)
    sr = ann_r / ann_v if ann_v > 0 else 0
    print(f"Skip {dow_names[skip_dow]:<10} {ann_r*100:>8.2f}%   {ann_v*100:>8.2f}%   {sr:>8.3f}")

print(f"\n{'Only Day':<14} {'Ann Ret':<12} {'Ann Vol':<12} {'Sharpe':<10}")
print("-" * 50)

for only_dow in range(5):
    only_ret = df_spy['Return'].copy()
    only_ret[df_spy['DOW'] != only_dow] = 0
    cum = np.cumprod(1 + only_ret.values)
    ann_r = cum[-1] ** (252 / len(only_ret)) - 1
    ann_v = np.std(only_ret.values) * np.sqrt(252)
    sr = ann_r / ann_v if ann_v > 0 else 0
    print(f"Only {dow_names[only_dow]:<10} {ann_r*100:>8.2f}%   {ann_v*100:>8.2f}%   {sr:>8.3f}")

# ============================================================
# 9. Monday Effect in High vs Low VIX Regimes
# ============================================================
print("\n" + "=" * 70)
print("SECTION 8: Monday Effect in High vs Low VIX Regimes")
print("=" * 70)

# Merge SPY with VIX
spy_df = data['SPY'].dropna(subset=['Return']).copy()
vix_close = data['^VIX']['Close'].rename('VIX')
spy_vix = spy_df.join(vix_close, how='inner')

vix_median = spy_vix['VIX'].median()
print(f"VIX median: {vix_median:.2f}")

for regime_name, mask in [('Low VIX', spy_vix['VIX'] <= vix_median),
                           ('High VIX', spy_vix['VIX'] > vix_median)]:
    regime_df = spy_vix[mask]

    print(f"\n--- {regime_name} Regime ---")
    print(f"{'Day':<12} {'Mean(%)':<10} {'N':<8} {'t-stat':<10} {'p-value':<10}")
    print("-" * 52)

    for dow in range(5):
        day_ret = regime_df[regime_df['DOW'] == dow]['Return'].values
        if len(day_ret) < 5:
            continue
        mean_r = np.mean(day_ret) * 100
        t, p = stats.ttest_1samp(day_ret, 0)
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"{dow_names[dow]:<12} {mean_r:>8.4f}  {len(day_ret):<8d} {t:>8.3f}  {p:>8.4f}  {sig}")

    # Monday specifically
    mon_ret = regime_df[regime_df['DOW'] == 0]['Return'].values
    non_mon_ret = regime_df[regime_df['DOW'] != 0]['Return'].values
    t_diff, p_diff = stats.ttest_ind(mon_ret, non_mon_ret)
    print(f"Monday vs Other days: t={t_diff:.4f}, p={p_diff:.4f}")

# ============================================================
# 10. Rolling Window Monday Effect
# ============================================================
print("\n" + "=" * 70)
print("SECTION 9: Rolling Window Monday Effect (5-year windows)")
print("=" * 70)

df_spy = data['SPY'].dropna(subset=['Return']).copy()

# 5-year rolling windows
window_years = 5
window_days = window_years * 252

years = sorted(df_spy.index.year.unique())
print(f"\n{'Window':<16} {'Mon Mean(%)':<14} {'Non-Mon Mean(%)':<16} {'Diff(%)':<12} {'t-stat':<10} {'p':<10}")
print("-" * 80)

for start_year in range(2005, 2021):
    end_year = start_year + window_years - 1
    mask = (df_spy.index.year >= start_year) & (df_spy.index.year <= end_year)
    window_df = df_spy[mask]

    mon = window_df[window_df['DOW'] == 0]['Return'].values
    non_mon = window_df[window_df['DOW'] != 0]['Return'].values

    if len(mon) < 50:
        continue

    mon_mean = np.mean(mon) * 100
    non_mean = np.mean(non_mon) * 100
    diff = mon_mean - non_mean
    t, p = stats.ttest_ind(mon, non_mon)
    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""

    print(f"{start_year}-{end_year}      {mon_mean:>10.4f}    {non_mean:>12.4f}    {diff:>8.4f}    {t:>8.3f}  {p:>8.4f}  {sig}")

# ============================================================
# 11. Bonferroni / Multiple Testing Correction
# ============================================================
print("\n" + "=" * 70)
print("SECTION 10: Multiple Testing Correction")
print("=" * 70)

# We tested 5 DOW x 2 assets = 10 comparisons for mean != 0
all_pvals = []
for asset_name in ['SPY', 'GLD']:
    df = data[asset_name].dropna(subset=['Return'])
    for dow in range(5):
        day_ret = df[df['DOW'] == dow]['Return'].values
        _, p = stats.ttest_1samp(day_ret, 0)
        all_pvals.append((f"{asset_name}_{dow_names[dow]}", p))

all_pvals.sort(key=lambda x: x[1])
n_tests = len(all_pvals)

print(f"\nBonferroni correction (alpha=0.05, {n_tests} tests):")
print(f"Adjusted alpha: {0.05/n_tests:.4f}")
print(f"\n{'Test':<20} {'p-value':<12} {'Bonf adj p':<14} {'BH adj p':<14} {'Sig (Bonf)?'}")
print("-" * 72)

# BH (Benjamini-Hochberg) correction
for rank, (name, p) in enumerate(all_pvals, 1):
    bonf_p = min(p * n_tests, 1.0)
    bh_p = min(p * n_tests / rank, 1.0)
    sig = "Yes" if bonf_p < 0.05 else ""
    print(f"{name:<20} {p:>10.6f}  {bonf_p:>12.6f}  {bh_p:>12.6f}  {sig}")

# ============================================================
# 12. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

# Key findings
spy_mon = results['SPY_monday_onesided']
gld_mon = results['GLD_monday_onesided']
spy_dow = results['SPY_dow']
gld_dow = results['GLD_dow']

print(f"""
1. MONDAY EFFECT ON RETURNS:
   SPY Monday: mean={spy_mon['mean_pct']:.4f}%, t={spy_mon['t_stat']:.3f},
     p(one-sided)={spy_mon['p_one_sided']:.4f}, frac_neg={spy_mon['frac_negative']*100:.1f}%
   GLD Monday: mean={gld_mon['mean_pct']:.4f}%, t={gld_mon['t_stat']:.3f},
     p(one-sided)={gld_mon['p_one_sided']:.4f}, frac_neg={gld_mon['frac_negative']*100:.1f}%

2. ANOVA (DOW MEANS EQUAL?):
   SPY: F={spy_dow['ANOVA_F']:.4f}, p={spy_dow['ANOVA_p']:.4f}
   GLD: F={gld_dow['ANOVA_F']:.4f}, p={gld_dow['ANOVA_p']:.4f}
   → {'DOW differences NOT significant' if spy_dow['ANOVA_p'] > 0.05 and gld_dow['ANOVA_p'] > 0.05 else 'Some DOW differences detected'}

3. FRIDAY-MONDAY LINK:
   SPY: Pearson r={results['SPY_fri_mon']['pearson_r']:.4f} (p={results['SPY_fri_mon']['pearson_p']:.4f})
   GLD: Pearson r={results['GLD_fri_mon']['pearson_r']:.4f} (p={results['GLD_fri_mon']['pearson_p']:.4f})

4. WEEKEND GAP:
   SPY: mean={results['SPY_fri_mon']['weekend_gap_mean_pct']:.4f}% (p={results['SPY_fri_mon']['weekend_gap_p']:.4f})
   GLD: mean={results['GLD_fri_mon']['weekend_gap_mean_pct']:.4f}% (p={results['GLD_fri_mon']['weekend_gap_p']:.4f})

5. VIX DOW PATTERN:
   ANOVA: F={results['VIX_dow']['ANOVA_F']:.4f}, p={results['VIX_dow']['ANOVA_p']:.4f}
   Weekend VIX change: mean={results['VIX_dow']['weekend_vix_change_pct']:.4f}% (p={results['VIX_dow']['weekend_vix_p']:.4f})

6. SKIP-MONDAY STRATEGY:
   SPY: Sharpe {results['SPY_strategy']['skip_mon_sharpe']:.3f} vs BnH {results['SPY_strategy']['bh_sharpe']:.3f}
   Net excess after TC: {results['SPY_strategy']['net_excess_after_tc']:.2f}%

CONCLUSION: {"Monday effect is NOT statistically significant in 2005-2024 data. No tradeable edge." if spy_mon['p_one_sided'] > 0.05 else "Monday effect IS statistically significant — further investigation warranted."}
Harvey (2016) threshold t>3.0: SPY Monday t={spy_mon['t_stat']:.3f} → {"FAILS" if abs(spy_mon['t_stat']) < 3.0 else "PASSES"}
""")

# Save results
results['metadata'] = {
    'experiment': 'K364',
    'title': 'Monday Effect Deep Dive',
    'data_source': 'yfinance',
    'assets': ['SPY', 'GLD', 'VIX'],
    'period': '2005-2024',
    'n_spy': int(data['SPY'].dropna(subset=['Return']).shape[0]),
    'n_gld': int(data['GLD'].dropna(subset=['Return']).shape[0]),
}

with open('experiments/k364_monday_effect_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("\nResults saved to experiments/k364_monday_effect_results.json")
print("Script saved to experiments/k364_monday_effect.py")
