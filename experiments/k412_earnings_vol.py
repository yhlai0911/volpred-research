"""
K412: Earnings Season Effect on Index Volatility
=================================================
Do Aggregate Earnings Drive SPY Vol?

Data: SPY, XLK, XLF daily from yfinance, 2005-2024
NO VIX, NO VT, NO 50/50.

Methodology:
1. Earnings season = 3rd-4th week of Jan/Apr/Jul/Oct
2. SPY vol (|return|, high-low range) during vs outside earnings
3. Pre-earnings drift and post-earnings reversal
4. Sector ETFs (XLK, XLF) during their heavy earnings weeks
5. Cross-decade comparison (2005-2014 vs 2015-2024)

[提出: User, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import warnings
import json
from datetime import datetime

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K412: Earnings Season Effect on Index Volatility")
print("=" * 70)

tickers = ['SPY', 'XLK', 'XLF']
data = {}
for t in tickers:
    print(f"Downloading {t}...")
    df = yf.download(t, start='2005-01-01', end='2025-01-01', auto_adjust=False, progress=False)
    # Flatten multi-level columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.index = pd.to_datetime(df.index)
    # Remove timezone info if present
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    data[t] = df
    print(f"  {t}: {len(df)} trading days, {df.index[0].date()} to {df.index[-1].date()}")

print()

# ============================================================
# 2. EARNINGS SEASON DEFINITION
# ============================================================
# Peak earnings weeks: 3rd and 4th week of Jan, Apr, Jul, Oct
# Week of month: ISO week number within that month

def is_earnings_season(date):
    """
    Returns True if date falls in 3rd or 4th week of Jan/Apr/Jul/Oct.
    Week of month = (day - 1) // 7 + 1
    """
    if date.month not in [1, 4, 7, 10]:
        return False
    week_of_month = (date.day - 1) // 7 + 1
    return week_of_month in [3, 4]

def get_earnings_period(date):
    """
    More granular classification:
    - 'pre_earnings': 1st-2nd week of earnings months
    - 'peak_earnings': 3rd-4th week of earnings months
    - 'post_earnings': 1st-2nd week of month after earnings months (Feb, May, Aug, Nov)
    - 'off_season': everything else
    """
    month = date.month
    week_of_month = (date.day - 1) // 7 + 1

    if month in [1, 4, 7, 10]:
        if week_of_month in [1, 2]:
            return 'pre_earnings'
        else:
            return 'peak_earnings'
    elif month in [2, 5, 8, 11]:
        if week_of_month in [1, 2]:
            return 'post_earnings'
        else:
            return 'off_season'
    else:
        return 'off_season'

# Apply classifications to SPY
spy = data['SPY'].copy()
spy['return'] = spy['Close'].pct_change()
spy['abs_return'] = spy['return'].abs()
spy['log_return'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['hl_range'] = (spy['High'] - spy['Low']) / spy['Close']  # normalized range
spy['is_earnings'] = spy.index.map(is_earnings_season)
spy['earnings_period'] = spy.index.map(get_earnings_period)
spy['year'] = spy.index.year
spy['decade'] = spy.index.map(lambda d: '2005-2014' if d.year <= 2014 else '2015-2024')
spy = spy.dropna(subset=['return'])

print(f"SPY total days: {len(spy)}")
print(f"Earnings season days: {spy['is_earnings'].sum()} ({spy['is_earnings'].mean()*100:.1f}%)")
print(f"Off-season days: {(~spy['is_earnings']).sum()} ({(~spy['is_earnings']).mean()*100:.1f}%)")
print()

# ============================================================
# 3. ANALYSIS 1: SPY VOL DURING VS OUTSIDE EARNINGS SEASON
# ============================================================
print("=" * 70)
print("ANALYSIS 1: SPY Volatility — Earnings Season vs Off-Season")
print("=" * 70)

earn_days = spy[spy['is_earnings']]
off_days = spy[~spy['is_earnings']]

metrics = {
    'Mean |return| (bps)': ('abs_return', lambda x: x.mean() * 10000),
    'Median |return| (bps)': ('abs_return', lambda x: x.median() * 10000),
    'Std of return (bps)': ('return', lambda x: x.std() * 10000),
    'Mean H-L range (bps)': ('hl_range', lambda x: x.mean() * 10000),
    'Annualized vol (%)': ('return', lambda x: x.std() * np.sqrt(252) * 100),
    'Skewness': ('return', lambda x: x.skew()),
    'Kurtosis': ('return', lambda x: x.kurtosis()),
}

print(f"\n{'Metric':<30} {'Earnings':>12} {'Off-Season':>12} {'Diff':>10} {'t-stat':>8} {'p-value':>8}")
print("-" * 80)

results_analysis1 = {}
for name, (col, func) in metrics.items():
    earn_val = func(earn_days[col])
    off_val = func(off_days[col])
    diff = earn_val - off_val

    # t-test for mean comparisons
    if 'Mean' in name or 'Annualized' in name or 'Std' in name:
        t_stat, p_val = stats.ttest_ind(earn_days[col].dropna(), off_days[col].dropna())
    else:
        # Mann-Whitney for non-mean metrics
        try:
            u_stat, p_val = stats.mannwhitneyu(earn_days[col].dropna(), off_days[col].dropna(), alternative='two-sided')
            t_stat = (u_stat - len(earn_days) * len(off_days) / 2) / np.sqrt(len(earn_days) * len(off_days) * (len(earn_days) + len(off_days) + 1) / 12)
        except:
            t_stat, p_val = np.nan, np.nan

    sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
    print(f"{name:<30} {earn_val:>12.2f} {off_val:>12.2f} {diff:>+10.2f} {t_stat:>8.2f} {p_val:>7.4f} {sig}")
    results_analysis1[name] = {
        'earnings': round(earn_val, 4),
        'off_season': round(off_val, 4),
        'diff': round(diff, 4),
        't_stat': round(t_stat, 4),
        'p_val': round(p_val, 4)
    }

# Welch's t-test specifically for |return|
t_welch, p_welch = stats.ttest_ind(earn_days['abs_return'].dropna(), off_days['abs_return'].dropna(), equal_var=False)
print(f"\nWelch's t-test on |return|: t={t_welch:.4f}, p={p_welch:.4f}")

# F-test for variance ratio
var_earn = earn_days['return'].var()
var_off = off_days['return'].var()
f_ratio = var_earn / var_off
df1, df2 = len(earn_days) - 1, len(off_days) - 1
p_f = 2 * min(stats.f.cdf(f_ratio, df1, df2), 1 - stats.f.cdf(f_ratio, df1, df2))
print(f"F-test for variance ratio: F={f_ratio:.4f}, p={p_f:.4f}")
print(f"  Earnings variance: {var_earn*10000:.4f} bps^2")
print(f"  Off-season variance: {var_off*10000:.4f} bps^2")

# ============================================================
# 4. ANALYSIS 2: HIGH-LOW RANGE (INTRADAY ACTIVITY)
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 2: Intraday Range (High-Low) During Earnings Season")
print("=" * 70)

# Percentile comparison
percentiles = [25, 50, 75, 90, 95]
print(f"\n{'Percentile':<15} {'Earnings (bps)':>15} {'Off-Season (bps)':>15} {'Ratio':>8}")
print("-" * 55)
for p in percentiles:
    earn_p = np.percentile(earn_days['hl_range'].dropna() * 10000, p)
    off_p = np.percentile(off_days['hl_range'].dropna() * 10000, p)
    ratio = earn_p / off_p if off_p != 0 else np.nan
    print(f"P{p:<14} {earn_p:>15.2f} {off_p:>15.2f} {ratio:>8.3f}")

# KS test for distribution difference
ks_stat, ks_p = stats.ks_2samp(earn_days['hl_range'].dropna(), off_days['hl_range'].dropna())
print(f"\nKS test (H-L range distributions): stat={ks_stat:.4f}, p={ks_p:.4f}")

# ============================================================
# 5. ANALYSIS 3: PRE-EARNINGS DRIFT AND POST-EARNINGS REVERSAL
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 3: Pre-Earnings Drift & Post-Earnings Reversal")
print("=" * 70)

period_stats = spy.groupby('earnings_period').agg(
    mean_return=('return', 'mean'),
    std_return=('return', 'std'),
    mean_abs_return=('abs_return', 'mean'),
    mean_range=('hl_range', 'mean'),
    count=('return', 'count'),
    cum_return=('return', 'sum')
).round(6)

# Annualize mean returns
period_stats['annualized_return_pct'] = period_stats['mean_return'] * 252 * 100
period_stats['annualized_vol_pct'] = period_stats['std_return'] * np.sqrt(252) * 100

print(f"\n{'Period':<16} {'Days':>6} {'Ann Ret%':>10} {'Ann Vol%':>10} {'Mean|r|bps':>11} {'Range bps':>10}")
print("-" * 65)
for period in ['pre_earnings', 'peak_earnings', 'post_earnings', 'off_season']:
    if period in period_stats.index:
        row = period_stats.loc[period]
        print(f"{period:<16} {row['count']:>6.0f} {row['annualized_return_pct']:>+10.2f} "
              f"{row['annualized_vol_pct']:>10.2f} {row['mean_abs_return']*10000:>11.2f} {row['mean_range']*10000:>10.2f}")

# ANOVA across periods
groups = [spy[spy['earnings_period'] == p]['return'].dropna() for p in ['pre_earnings', 'peak_earnings', 'post_earnings', 'off_season']]
f_anova, p_anova = stats.f_oneway(*groups)
print(f"\nANOVA for mean return across periods: F={f_anova:.4f}, p={p_anova:.4f}")

# ANOVA for volatility (|return|)
groups_vol = [spy[spy['earnings_period'] == p]['abs_return'].dropna() for p in ['pre_earnings', 'peak_earnings', 'post_earnings', 'off_season']]
f_anova_vol, p_anova_vol = stats.f_oneway(*groups_vol)
print(f"ANOVA for |return| across periods: F={f_anova_vol:.4f}, p={p_anova_vol:.4f}")

# Pairwise t-tests: pre vs peak, peak vs post
for pair_name, (p1, p2) in [('Pre vs Peak', ('pre_earnings', 'peak_earnings')),
                              ('Peak vs Post', ('peak_earnings', 'post_earnings')),
                              ('Peak vs Off', ('peak_earnings', 'off_season')),
                              ('Pre vs Off', ('pre_earnings', 'off_season'))]:
    g1 = spy[spy['earnings_period'] == p1]['return'].dropna()
    g2 = spy[spy['earnings_period'] == p2]['return'].dropna()
    t, p = stats.ttest_ind(g1, g2)
    print(f"  {pair_name}: t={t:.4f}, p={p:.4f} (mean: {g1.mean()*10000:.2f} vs {g2.mean()*10000:.2f} bps)")

# ============================================================
# 6. ANALYSIS 4: SECTOR ETFs DURING EARNINGS
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 4: Sector ETFs (XLK, XLF) During Earnings Season")
print("=" * 70)

# XLK (tech): heavy earnings in Jan (Q4 results) and Apr (Q1 results)
# XLF (financials): banks report early, 2nd week of Jan/Apr/Jul/Oct

def is_tech_earnings(date):
    """XLK heavy earnings: 3rd-4th week of Jan and Apr primarily"""
    if date.month in [1, 4]:
        week_of_month = (date.day - 1) // 7 + 1
        return week_of_month in [3, 4]
    return False

def is_bank_earnings(date):
    """XLF bank earnings: 2nd-3rd week of Jan/Apr/Jul/Oct (banks report early)"""
    if date.month in [1, 4, 7, 10]:
        week_of_month = (date.day - 1) // 7 + 1
        return week_of_month in [2, 3]
    return False

for ticker, sector_name, sector_func in [
    ('XLK', 'Tech (XLK)', is_tech_earnings),
    ('XLF', 'Financials (XLF)', is_bank_earnings)
]:
    df = data[ticker].copy()
    df['return'] = df['Close'].pct_change()
    df['abs_return'] = df['return'].abs()
    df['hl_range'] = (df['High'] - df['Low']) / df['Close']
    df['is_sector_earnings'] = df.index.map(sector_func)
    df['is_general_earnings'] = df.index.map(is_earnings_season)
    df = df.dropna(subset=['return'])

    sector_earn = df[df['is_sector_earnings']]
    sector_off = df[~df['is_sector_earnings']]
    general_earn = df[df['is_general_earnings']]

    print(f"\n--- {sector_name} ---")
    print(f"Sector earnings days: {len(sector_earn)}, Off-season: {len(sector_off)}")

    # Vol comparison
    t_abs, p_abs = stats.ttest_ind(sector_earn['abs_return'].dropna(), sector_off['abs_return'].dropna(), equal_var=False)
    t_range, p_range = stats.ttest_ind(sector_earn['hl_range'].dropna(), sector_off['hl_range'].dropna(), equal_var=False)

    print(f"  Mean |return| — Earnings: {sector_earn['abs_return'].mean()*10000:.2f} bps, Off: {sector_off['abs_return'].mean()*10000:.2f} bps")
    print(f"    Welch t={t_abs:.4f}, p={p_abs:.4f}")
    print(f"  Mean H-L range — Earnings: {sector_earn['hl_range'].mean()*10000:.2f} bps, Off: {sector_off['hl_range'].mean()*10000:.2f} bps")
    print(f"    Welch t={t_range:.4f}, p={p_range:.4f}")

    # Compare sector vs SPY during sector's earnings
    spy_matching = spy.loc[spy.index.isin(sector_earn.index)]
    if len(spy_matching) > 10:
        sector_vol = sector_earn['abs_return'].mean()
        spy_vol = spy_matching['abs_return'].mean()
        ratio = sector_vol / spy_vol if spy_vol != 0 else np.nan
        print(f"  Sector/SPY vol ratio during sector earnings: {ratio:.3f}")
        # Paired test
        merged = pd.merge(sector_earn[['abs_return']], spy_matching[['abs_return']],
                         left_index=True, right_index=True, suffixes=('_sector', '_spy'))
        t_paired, p_paired = stats.ttest_rel(merged['abs_return_sector'], merged['abs_return_spy'])
        print(f"    Paired t-test (sector vs SPY): t={t_paired:.4f}, p={p_paired:.4f}")

# ============================================================
# 7. ANALYSIS 5: CROSS-DECADE COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 5: Cross-Decade — Has Earnings Effect Changed?")
print("=" * 70)

for decade in ['2005-2014', '2015-2024']:
    sub = spy[spy['decade'] == decade]
    earn = sub[sub['is_earnings']]
    off = sub[~sub['is_earnings']]

    earn_vol = earn['abs_return'].mean() * 10000
    off_vol = off['abs_return'].mean() * 10000
    earn_range = earn['hl_range'].mean() * 10000
    off_range = off['hl_range'].mean() * 10000

    t, p = stats.ttest_ind(earn['abs_return'].dropna(), off['abs_return'].dropna(), equal_var=False)
    t_r, p_r = stats.ttest_ind(earn['hl_range'].dropna(), off['hl_range'].dropna(), equal_var=False)

    print(f"\n--- {decade} ---")
    print(f"  Earnings days: {len(earn)}, Off-season: {len(off)}")
    print(f"  Mean |return| — Earn: {earn_vol:.2f} bps, Off: {off_vol:.2f} bps, Diff: {earn_vol-off_vol:+.2f} bps")
    print(f"    t={t:.4f}, p={p:.4f}")
    print(f"  Mean H-L range — Earn: {earn_range:.2f} bps, Off: {off_range:.2f} bps, Diff: {earn_range-off_range:+.2f} bps")
    print(f"    t={t_r:.4f}, p={p_r:.4f}")

    # Per-period breakdown
    for period in ['pre_earnings', 'peak_earnings', 'post_earnings', 'off_season']:
        psub = sub[sub['earnings_period'] == period]
        print(f"    {period:<16}: ret={psub['return'].mean()*10000:+.2f} bps/day, vol={psub['abs_return'].mean()*10000:.2f} bps, n={len(psub)}")

# ============================================================
# 8. ANALYSIS 6: MONTHLY PATTERN (which month has highest vol?)
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 6: Monthly Volatility Pattern")
print("=" * 70)

monthly = spy.groupby(spy.index.month).agg(
    mean_abs_return=('abs_return', 'mean'),
    mean_range=('hl_range', 'mean'),
    mean_return=('return', 'mean'),
    std_return=('return', 'std'),
    count=('return', 'count')
)

month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
print(f"\n{'Month':<6} {'Mean|r|bps':>11} {'Range bps':>10} {'Ann Ret%':>10} {'Ann Vol%':>10} {'N':>6}")
print("-" * 55)
for m in range(1, 13):
    row = monthly.loc[m]
    is_earn = '*' if m in [1, 4, 7, 10] else ' '
    print(f"{month_names[m-1]}{is_earn:<5} {row['mean_abs_return']*10000:>11.2f} {row['mean_range']*10000:>10.2f} "
          f"{row['mean_return']*252*100:>+10.2f} {row['std_return']*np.sqrt(252)*100:>10.2f} {row['count']:>6.0f}")
print("* = Earnings month (Jan/Apr/Jul/Oct)")

# Kruskal-Wallis test across months
monthly_groups = [spy[spy.index.month == m]['abs_return'].dropna() for m in range(1, 13)]
h_stat, p_kw = stats.kruskal(*monthly_groups)
print(f"\nKruskal-Wallis test across months (|return|): H={h_stat:.4f}, p={p_kw:.4f}")

# Compare earnings months vs non-earnings months
earn_months = spy[spy.index.month.isin([1, 4, 7, 10])]['abs_return']
non_earn_months = spy[~spy.index.month.isin([1, 4, 7, 10])]['abs_return']
t_monthly, p_monthly = stats.ttest_ind(earn_months.dropna(), non_earn_months.dropna(), equal_var=False)
print(f"Earnings months vs non-earnings months: t={t_monthly:.4f}, p={p_monthly:.4f}")
print(f"  Earnings months mean: {earn_months.mean()*10000:.2f} bps, Non-earnings: {non_earn_months.mean()*10000:.2f} bps")

# ============================================================
# 9. ANALYSIS 7: CONDITIONAL VOLATILITY — DOES EARNINGS SEASON
#    PREDICT NEXT-WEEK VOL?
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 7: Does Earnings Season Predict Next-Week Realized Vol?")
print("=" * 70)

# Compute weekly realized vol
spy_weekly = spy['return'].resample('W').agg(['std', 'count', 'sum'])
spy_weekly.columns = ['weekly_vol', 'n_days', 'weekly_return']
spy_weekly = spy_weekly[spy_weekly['n_days'] >= 3]  # at least 3 trading days

# Classify each week
spy_weekly['is_earnings_week'] = spy_weekly.index.map(
    lambda d: d.month in [1, 4, 7, 10] and (d.day - 1) // 7 + 1 in [3, 4, 5]
)
spy_weekly['next_week_vol'] = spy_weekly['weekly_vol'].shift(-1)
spy_weekly = spy_weekly.dropna()

earn_weeks = spy_weekly[spy_weekly['is_earnings_week']]
off_weeks = spy_weekly[~spy_weekly['is_earnings_week']]

print(f"\nEarnings weeks: {len(earn_weeks)}, Off-season weeks: {len(off_weeks)}")
print(f"Current-week vol — Earn: {earn_weeks['weekly_vol'].mean()*10000:.2f} bps, Off: {off_weeks['weekly_vol'].mean()*10000:.2f} bps")
t_curr, p_curr = stats.ttest_ind(earn_weeks['weekly_vol'].dropna(), off_weeks['weekly_vol'].dropna(), equal_var=False)
print(f"  t={t_curr:.4f}, p={p_curr:.4f}")

print(f"Next-week vol — Earn: {earn_weeks['next_week_vol'].mean()*10000:.2f} bps, Off: {off_weeks['next_week_vol'].mean()*10000:.2f} bps")
t_next, p_next = stats.ttest_ind(earn_weeks['next_week_vol'].dropna(), off_weeks['next_week_vol'].dropna(), equal_var=False)
print(f"  t={t_next:.4f}, p={p_next:.4f}")

# ============================================================
# 10. ANALYSIS 8: BOOTSTRAP CONFIDENCE INTERVALS
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 8: Bootstrap Confidence Intervals for Earnings Effect")
print("=" * 70)

np.random.seed(42)
n_boot = 10000
boot_diffs = np.zeros(n_boot)

earn_abs = earn_days['abs_return'].dropna().values
off_abs = off_days['abs_return'].dropna().values
observed_diff = earn_abs.mean() - off_abs.mean()

for i in range(n_boot):
    boot_earn = np.random.choice(earn_abs, size=len(earn_abs), replace=True)
    boot_off = np.random.choice(off_abs, size=len(off_abs), replace=True)
    boot_diffs[i] = boot_earn.mean() - boot_off.mean()

ci_lower = np.percentile(boot_diffs, 2.5)
ci_upper = np.percentile(boot_diffs, 97.5)
boot_se = boot_diffs.std()
boot_t = observed_diff / boot_se if boot_se > 0 else 0

print(f"\nObserved difference (|return|): {observed_diff*10000:.4f} bps")
print(f"Bootstrap 95% CI: [{ci_lower*10000:.4f}, {ci_upper*10000:.4f}] bps")
print(f"Bootstrap SE: {boot_se*10000:.4f} bps")
print(f"Bootstrap t-stat: {boot_t:.4f}")
print(f"CI includes zero: {'Yes' if ci_lower <= 0 <= ci_upper else 'No'}")

# Same for H-L range
earn_range_vals = earn_days['hl_range'].dropna().values
off_range_vals = off_days['hl_range'].dropna().values
observed_diff_range = earn_range_vals.mean() - off_range_vals.mean()

boot_diffs_range = np.zeros(n_boot)
for i in range(n_boot):
    be = np.random.choice(earn_range_vals, size=len(earn_range_vals), replace=True)
    bo = np.random.choice(off_range_vals, size=len(off_range_vals), replace=True)
    boot_diffs_range[i] = be.mean() - bo.mean()

ci_lower_r = np.percentile(boot_diffs_range, 2.5)
ci_upper_r = np.percentile(boot_diffs_range, 97.5)
print(f"\nObserved difference (H-L range): {observed_diff_range*10000:.4f} bps")
print(f"Bootstrap 95% CI: [{ci_lower_r*10000:.4f}, {ci_upper_r*10000:.4f}] bps")
print(f"CI includes zero: {'Yes' if ci_lower_r <= 0 <= ci_upper_r else 'No'}")

# ============================================================
# 11. ANALYSIS 9: YEAR-BY-YEAR EARNINGS EFFECT
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 9: Year-by-Year Earnings Season Effect")
print("=" * 70)

print(f"\n{'Year':<6} {'Earn|r|bps':>11} {'Off|r|bps':>11} {'Diff bps':>10} {'t-stat':>8} {'p-val':>8} {'N_earn':>7} {'N_off':>6}")
print("-" * 75)

year_results = {}
positive_years = 0
total_years = 0

for year in range(2005, 2025):
    sub = spy[spy['year'] == year]
    earn = sub[sub['is_earnings']]
    off = sub[~sub['is_earnings']]

    if len(earn) < 5 or len(off) < 20:
        continue

    earn_vol = earn['abs_return'].mean() * 10000
    off_vol = off['abs_return'].mean() * 10000
    diff = earn_vol - off_vol
    t, p = stats.ttest_ind(earn['abs_return'].dropna(), off['abs_return'].dropna(), equal_var=False)

    sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
    print(f"{year:<6} {earn_vol:>11.2f} {off_vol:>11.2f} {diff:>+10.2f} {t:>8.3f} {p:>8.4f} {len(earn):>7} {len(off):>6} {sig}")

    year_results[year] = {'diff_bps': round(diff, 2), 't_stat': round(t, 4), 'p_val': round(p, 4)}
    total_years += 1
    if diff > 0:
        positive_years += 1

print(f"\nYears with higher earnings vol: {positive_years}/{total_years} ({positive_years/total_years*100:.1f}%)")

# Binomial test: is the proportion different from 50%?
binom_result = stats.binomtest(positive_years, total_years, 0.5, alternative='two-sided')
binom_p = binom_result.pvalue
print(f"Binomial test (H0: 50% positive): p={binom_p:.4f}")

# ============================================================
# 12. ANALYSIS 10: EARNINGS SEASON × MARKET REGIME INTERACTION
# ============================================================
print("\n" + "=" * 70)
print("ANALYSIS 10: Earnings Effect in Bull vs Bear Markets")
print("=" * 70)

# Use 200-day moving average to define bull/bear
spy['sma200'] = spy['Close'].rolling(200).mean()
spy['is_bull'] = spy['Close'] > spy['sma200']

for regime, label in [(True, 'Bull (above SMA200)'), (False, 'Bear (below SMA200)')]:
    sub = spy[spy['is_bull'] == regime].dropna(subset=['sma200'])
    earn = sub[sub['is_earnings']]
    off = sub[~sub['is_earnings']]

    if len(earn) < 20 or len(off) < 50:
        continue

    earn_vol = earn['abs_return'].mean() * 10000
    off_vol = off['abs_return'].mean() * 10000
    t, p = stats.ttest_ind(earn['abs_return'].dropna(), off['abs_return'].dropna(), equal_var=False)

    print(f"\n{label}: n_earn={len(earn)}, n_off={len(off)}")
    print(f"  Earnings vol: {earn_vol:.2f} bps, Off-season: {off_vol:.2f} bps, Diff: {earn_vol-off_vol:+.2f} bps")
    print(f"  t={t:.4f}, p={p:.4f}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("K412 SUMMARY")
print("=" * 70)

print("""
Data: SPY/XLK/XLF daily, 2005-2024 (yfinance). ~5000 trading days.
Earnings season: 3rd-4th week of Jan/Apr/Jul/Oct.

Key Findings:
""")

# Determine significance
abs_return_sig = results_analysis1['Mean |return| (bps)']['p_val'] < 0.05
range_sig = results_analysis1['Mean H-L range (bps)']['p_val'] < 0.05
earn_ret = results_analysis1['Mean |return| (bps)']['earnings']
off_ret = results_analysis1['Mean |return| (bps)']['off_season']
diff_ret = results_analysis1['Mean |return| (bps)']['diff']
p_ret = results_analysis1['Mean |return| (bps)']['p_val']

# Note: results_analysis1 values are already raw (not in bps), use *10000 to convert
# But earn_ret etc. were stored after round() from the metric func which already did *10000
# So earn_ret is already in bps units -- don't multiply again
print(f"1. Earnings vol effect: {'SIGNIFICANT' if abs_return_sig else 'NOT SIGNIFICANT'}")
print(f"   Earnings |return|={earn_ret:.2f} bps vs Off={off_ret:.2f} bps, diff={diff_ret:+.2f} bps, p={p_ret:.4f}")
print(f"   Bootstrap CI: [{ci_lower*10000:.2f}, {ci_upper*10000:.2f}] bps")

earn_range_val = results_analysis1['Mean H-L range (bps)']['earnings']
off_range_val = results_analysis1['Mean H-L range (bps)']['off_season']
diff_range_val = results_analysis1['Mean H-L range (bps)']['diff']
p_range_val = results_analysis1['Mean H-L range (bps)']['p_val']

print(f"\n2. Intraday range effect: {'SIGNIFICANT' if range_sig else 'NOT SIGNIFICANT'}")
print(f"   Earnings range={earn_range_val:.2f} bps vs Off={off_range_val:.2f} bps, diff={diff_range_val:+.2f} bps, p={p_range_val:.4f}")

print(f"\n3. Pre-earnings drift: ANOVA p={p_anova:.4f}")
print(f"   Vol across periods: ANOVA p={p_anova_vol:.4f}")

print(f"\n4. Cross-decade stability: see decade breakdown above")
print(f"\n5. Year-by-year: {positive_years}/{total_years} years show higher earnings vol")
print(f"   Binomial test p={binom_p:.4f}")

print(f"\n6. Monthly Kruskal-Wallis: H={h_stat:.4f}, p={p_kw:.4f}")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment': 'K412',
    'title': 'Earnings Season Effect on Index Volatility',
    'data': 'SPY/XLK/XLF daily, 2005-2024, yfinance',
    'n_total_days': len(spy),
    'n_earnings_days': int(spy['is_earnings'].sum()),
    'n_off_season_days': int((~spy['is_earnings']).sum()),
    'analysis1_vol_comparison': results_analysis1,
    'welch_t_absreturn': {'t': round(t_welch, 4), 'p': round(p_welch, 4)},
    'f_test_variance': {'F': round(f_ratio, 4), 'p': round(p_f, 4)},
    'ks_test_range': {'stat': round(ks_stat, 4), 'p': round(ks_p, 4)},
    'anova_return_across_periods': {'F': round(f_anova, 4), 'p': round(p_anova, 4)},
    'anova_vol_across_periods': {'F': round(f_anova_vol, 4), 'p': round(p_anova_vol, 4)},
    'bootstrap': {
        'observed_diff_bps': round(observed_diff * 10000, 4),
        'ci_95_lower_bps': round(ci_lower * 10000, 4),
        'ci_95_upper_bps': round(ci_upper * 10000, 4),
        'boot_t': round(boot_t, 4),
        'ci_includes_zero': bool(ci_lower <= 0 <= ci_upper)
    },
    'bootstrap_range': {
        'observed_diff_bps': round(observed_diff_range * 10000, 4),
        'ci_95_lower_bps': round(ci_lower_r * 10000, 4),
        'ci_95_upper_bps': round(ci_upper_r * 10000, 4),
        'ci_includes_zero': bool(ci_lower_r <= 0 <= ci_upper_r)
    },
    'year_by_year': year_results,
    'positive_years_fraction': f"{positive_years}/{total_years}",
    'binomial_test_p': round(binom_p, 4),
    'monthly_kruskal_wallis': {'H': round(h_stat, 4), 'p': round(p_kw, 4)},
    'weekly_vol_prediction': {
        'current_week_t': round(t_curr, 4),
        'current_week_p': round(p_curr, 4),
        'next_week_t': round(t_next, 4),
        'next_week_p': round(p_next, 4)
    },
    'timestamp': datetime.now().isoformat()
}

with open('experiments/k412_earnings_vol_results.json', 'w') as f:
    json.dump(results, f, indent=2)

print("\nResults saved to experiments/k412_earnings_vol_results.json")
print("Script saved to experiments/k412_earnings_vol.py")
