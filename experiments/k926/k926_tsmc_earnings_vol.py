#!/usr/bin/env python3
"""
K926: TSMC Earnings/Revenue Announcement Volatility — 0050.TW Event Study

Research Question:
  How do TSMC's quarterly earnings calls and monthly revenue announcements
  affect 0050.TW (Taiwan Top 50 ETF) volatility?

Data Sources:
  - yfinance: 0050.TW, 2330.TW daily OHLCV (2015-2026)
  - TSMC IR: manually compiled quarterly earnings dates
  - Monthly revenue announcement dates: ~10th of each month

Method:
  - Event window [-5, +5] around each event
  - |return| as volatility proxy
  - t-test: event-day |return| vs non-event-day |return|
  - TSMC → 0050.TW beta on event days vs normal days
  - Quarterly earnings vs monthly revenue comparison

References:
  - MacKinlay (1997): Event studies in economics and finance, JEL
  - Patell & Wolfson (1984): The intraday speed of adjustment
"""

import numpy as np
np.random.seed(42)

import pandas as pd
import yfinance as yf
import json
import os
from datetime import datetime, timezone
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import warnings
warnings.filterwarnings('ignore')

# Import 0050.TW data cleaner
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from volpred.utils import clean_tw50_data

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# Step 1: TSMC Quarterly Earnings Call Dates (Investor Conferences)
# ============================================================
# Source: TSMC Investor Relations (https://investor.tsmc.com)
# These are the dates of TSMC's quarterly earnings conference calls.
# The market reacts on the trading day of or after the call.
# Format: YYYY-MM-DD (date of the conference call, typically after market close or pre-market next day)

TSMC_EARNINGS_DATES = [
    # 2015
    '2015-01-15', '2015-04-16', '2015-07-16', '2015-10-15',
    # 2016
    '2016-01-14', '2016-04-14', '2016-07-14', '2016-10-13',
    # 2017
    '2017-01-12', '2017-04-13', '2017-07-13', '2017-10-19',
    # 2018
    '2018-01-18', '2018-04-19', '2018-07-19', '2018-10-18',
    # 2019
    '2019-01-17', '2019-04-18', '2019-07-18', '2019-10-17',
    # 2020
    '2020-01-16', '2020-04-16', '2020-07-16', '2020-10-15',
    # 2021
    '2021-01-14', '2021-04-15', '2021-07-15', '2021-10-14',
    # 2022
    '2022-01-13', '2022-04-14', '2022-07-14', '2022-10-13',
    # 2023
    '2023-01-12', '2023-04-20', '2023-07-20', '2023-10-19',
    # 2024
    '2024-01-18', '2024-04-18', '2024-07-18', '2024-10-17',
    # 2025
    '2025-01-16', '2025-04-17', '2025-07-17', '2025-10-16',
    # 2026
    '2026-01-15', '2026-04-16',
]

# TSMC monthly revenue announcement dates (typically around the 10th)
# We'll generate these programmatically and match to nearest trading day
def generate_monthly_revenue_dates(start_year=2015, end_year=2026):
    """Generate TSMC monthly revenue announcement dates.
    TSMC announces previous month's revenue by the 10th of each month.
    If 10th is weekend/holiday, the announcement is on the nearest business day."""
    dates = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # Revenue for month M-1 is announced around the 10th of month M
            # Skip if we're past current date
            d = f'{year}-{month:02d}-10'
            try:
                dt = pd.Timestamp(d)
                if dt <= pd.Timestamp.now():
                    dates.append(d)
            except:
                pass
    return dates

TSMC_REVENUE_DATES = generate_monthly_revenue_dates()

# ============================================================
# Step 2: Download Data
# ============================================================
print("=" * 70)
print("K926: TSMC Earnings/Revenue — 0050.TW Event Study")
print("=" * 70)

print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2014-01-01', end='2026-04-07', progress=False)
tsmc = yf.download('2330.TW', start='2014-01-01', end='2026-04-07', progress=False)

# Handle MultiIndex columns from yfinance
if isinstance(tw50.columns, pd.MultiIndex):
    tw50.columns = tw50.columns.get_level_values(0)
if isinstance(tsmc.columns, pd.MultiIndex):
    tsmc.columns = tsmc.columns.get_level_values(0)

# Clean 0050.TW data (split adjustment)
tw50_prices = tw50['Close'].copy()
tw50_prices, tw50_returns = clean_tw50_data(tw50_prices)
tw50['Close'] = tw50_prices
tw50['Return'] = tw50_returns

# TSMC returns
tsmc['Return'] = tsmc['Close'].pct_change()

print(f"  0050.TW: {len(tw50)} trading days ({tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')})")
print(f"  2330.TW: {len(tsmc)} trading days ({tsmc.index[0].strftime('%Y-%m-%d')} to {tsmc.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# Step 3: Match event dates to trading days
# ============================================================
print("\n[2] Matching event dates to trading days...")

trading_days = tw50.index

def match_to_trading_day(date_str, trading_days):
    """Match a calendar date to the nearest trading day (same or next)."""
    dt = pd.Timestamp(date_str)
    # Find nearest trading day on or after the date
    future_days = trading_days[trading_days >= dt]
    if len(future_days) > 0:
        return future_days[0]
    # If no future day, find nearest before
    past_days = trading_days[trading_days <= dt]
    if len(past_days) > 0:
        return past_days[-1]
    return None

# Match earnings dates
earnings_trading_days = []
for d in TSMC_EARNINGS_DATES:
    td = match_to_trading_day(d, trading_days)
    if td is not None and td >= trading_days[0] and td <= trading_days[-1]:
        earnings_trading_days.append(td)
earnings_trading_days = pd.DatetimeIndex(sorted(set(earnings_trading_days)))

# Match revenue dates
revenue_trading_days = []
for d in TSMC_REVENUE_DATES:
    td = match_to_trading_day(d, trading_days)
    if td is not None and td >= trading_days[0] and td <= trading_days[-1]:
        revenue_trading_days.append(td)
revenue_trading_days = pd.DatetimeIndex(sorted(set(revenue_trading_days)))

# Remove revenue dates that overlap with earnings dates (within 3 days)
# to isolate the effects
revenue_only = []
for rd in revenue_trading_days:
    is_near_earnings = any(abs((rd - ed).days) <= 3 for ed in earnings_trading_days)
    if not is_near_earnings:
        revenue_only.append(rd)
revenue_only = pd.DatetimeIndex(revenue_only)

print(f"  Quarterly earnings events: {len(earnings_trading_days)}")
print(f"  Monthly revenue events (total): {len(revenue_trading_days)}")
print(f"  Monthly revenue events (excl. near-earnings): {len(revenue_only)}")

# ============================================================
# Step 4: Event Window Analysis
# ============================================================
print("\n[3] Event window analysis [-5, +5]...")

def event_window_analysis(event_dates, returns_series, window=5):
    """Compute average returns and |returns| in event windows."""
    all_windows = []
    for event_date in event_dates:
        idx = returns_series.index.get_indexer([event_date], method='nearest')[0]
        if idx - window < 0 or idx + window >= len(returns_series):
            continue
        window_data = returns_series.iloc[idx - window: idx + window + 1].values
        if len(window_data) == 2 * window + 1 and not np.any(np.isnan(window_data)):
            all_windows.append(window_data)

    if len(all_windows) == 0:
        return None, None, 0

    all_windows = np.array(all_windows)
    avg_return = np.mean(all_windows, axis=0)
    avg_abs_return = np.mean(np.abs(all_windows), axis=0)
    return avg_return, avg_abs_return, len(all_windows)

# 0050.TW event windows
tw50_ret = tw50['Return'].dropna()

# Earnings
earn_ret, earn_abs, earn_n = event_window_analysis(earnings_trading_days, tw50_ret, window=5)
# Revenue
rev_ret, rev_abs, rev_n = event_window_analysis(revenue_only, tw50_ret, window=5)

print(f"  Earnings events with valid windows: {earn_n}")
print(f"  Revenue events with valid windows: {rev_n}")

# ============================================================
# Step 5: Event-day vs Non-event-day comparison
# ============================================================
print("\n[4] Event-day vs Non-event-day |return| comparison...")

# Define event days: day 0 and day +1 (reaction day)
def get_event_reaction_days(event_dates, trading_days, reaction_window=1):
    """Get the set of event days and their reaction days."""
    all_days = set()
    for ed in event_dates:
        idx = trading_days.get_indexer([ed], method='nearest')[0]
        for offset in range(0, reaction_window + 1):
            if idx + offset < len(trading_days):
                all_days.add(trading_days[idx + offset])
    return all_days

# Earnings event + reaction days (day 0, +1)
earnings_event_set = get_event_reaction_days(earnings_trading_days, trading_days, reaction_window=1)
# Revenue event + reaction days
revenue_event_set = get_event_reaction_days(revenue_only, trading_days, reaction_window=1)
# All TSMC events
all_tsmc_event_set = earnings_event_set | revenue_event_set

# Non-event days
all_event_set = all_tsmc_event_set
non_event_mask = ~tw50_ret.index.isin(all_event_set)
event_mask_earnings = tw50_ret.index.isin(earnings_event_set)
event_mask_revenue = tw50_ret.index.isin(revenue_event_set)
event_mask_all = tw50_ret.index.isin(all_tsmc_event_set)

abs_ret = tw50_ret.abs()
non_event_abs = abs_ret[non_event_mask]
earnings_abs = abs_ret[event_mask_earnings]
revenue_abs = abs_ret[event_mask_revenue]
all_event_abs = abs_ret[event_mask_all]

# Stats
def compute_event_stats(event_abs, non_event_abs, label):
    """Compute event vs non-event statistics and t-test."""
    mean_event = event_abs.mean()
    mean_non = non_event_abs.mean()
    ratio = mean_event / mean_non if mean_non > 0 else np.nan

    # Welch's t-test
    t_stat, p_value = stats.ttest_ind(event_abs.values, non_event_abs.values, equal_var=False)

    # Effect size (Cohen's d)
    pooled_std = np.sqrt((event_abs.std()**2 + non_event_abs.std()**2) / 2)
    cohens_d = (mean_event - mean_non) / pooled_std if pooled_std > 0 else 0

    print(f"\n  {label}:")
    print(f"    Event days: n={len(event_abs)}, mean |ret| = {mean_event:.4f} ({mean_event*100:.2f}%)")
    print(f"    Non-event:  n={len(non_event_abs)}, mean |ret| = {mean_non:.4f} ({mean_non*100:.2f}%)")
    print(f"    Ratio: {ratio:.2f}x")
    print(f"    t-stat: {t_stat:.3f}, p-value: {p_value:.4f}")
    print(f"    Cohen's d: {cohens_d:.3f}")
    print(f"    Significant at 5%: {'YES' if p_value < 0.05 else 'NO'}")

    return {
        'n_event': len(event_abs),
        'n_non_event': len(non_event_abs),
        'mean_event_abs_ret': float(mean_event),
        'mean_non_event_abs_ret': float(mean_non),
        'ratio': float(ratio),
        't_stat': float(t_stat),
        'p_value': float(p_value),
        'cohens_d': float(cohens_d),
        'significant_5pct': bool(p_value < 0.05),
    }

stats_earnings = compute_event_stats(earnings_abs, non_event_abs, "Quarterly Earnings")
stats_revenue = compute_event_stats(revenue_abs, non_event_abs, "Monthly Revenue")
stats_all = compute_event_stats(all_event_abs, non_event_abs, "All TSMC Events")

# ============================================================
# Step 6: TSMC → 0050.TW Transmission
# ============================================================
print("\n[5] TSMC → 0050.TW transmission analysis...")

# Align TSMC and 0050.TW returns
common_idx = tw50_ret.index.intersection(tsmc['Return'].dropna().index)
tw50_aligned = tw50_ret.loc[common_idx]
tsmc_aligned = tsmc['Return'].loc[common_idx]

# Overall beta
from numpy.polynomial.polynomial import polyfit
beta_all = np.cov(tw50_aligned.values, tsmc_aligned.values)[0,1] / np.var(tsmc_aligned.values)
corr_all = np.corrcoef(tw50_aligned.values, tsmc_aligned.values)[0,1]

# Beta on earnings event days
earn_mask = common_idx.isin(earnings_event_set)
if earn_mask.sum() > 5:
    tw50_earn = tw50_aligned[earn_mask]
    tsmc_earn = tsmc_aligned[earn_mask]
    beta_earn = np.cov(tw50_earn.values, tsmc_earn.values)[0,1] / np.var(tsmc_earn.values) if np.var(tsmc_earn.values) > 0 else np.nan
    corr_earn = np.corrcoef(tw50_earn.values, tsmc_earn.values)[0,1]
else:
    beta_earn = np.nan
    corr_earn = np.nan

# Beta on revenue event days
rev_mask = common_idx.isin(revenue_event_set)
if rev_mask.sum() > 5:
    tw50_rev = tw50_aligned[rev_mask]
    tsmc_rev = tsmc_aligned[rev_mask]
    beta_rev = np.cov(tw50_rev.values, tsmc_rev.values)[0,1] / np.var(tsmc_rev.values) if np.var(tsmc_rev.values) > 0 else np.nan
    corr_rev = np.corrcoef(tw50_rev.values, tsmc_rev.values)[0,1]
else:
    beta_rev = np.nan
    corr_rev = np.nan

# Non-event beta
non_ev_mask = ~common_idx.isin(all_tsmc_event_set)
if non_ev_mask.sum() > 5:
    tw50_non = tw50_aligned[non_ev_mask]
    tsmc_non = tsmc_aligned[non_ev_mask]
    beta_non = np.cov(tw50_non.values, tsmc_non.values)[0,1] / np.var(tsmc_non.values) if np.var(tsmc_non.values) > 0 else np.nan
    corr_non = np.corrcoef(tw50_non.values, tsmc_non.values)[0,1]
else:
    beta_non = np.nan
    corr_non = np.nan

print(f"  Overall:        beta={beta_all:.3f}, corr={corr_all:.3f}")
print(f"  Earnings days:  beta={beta_earn:.3f}, corr={corr_earn:.3f}")
print(f"  Revenue days:   beta={beta_rev:.3f}, corr={corr_rev:.3f}")
print(f"  Non-event days: beta={beta_non:.3f}, corr={corr_non:.3f}")

# Test if beta is significantly different on event days
# Bootstrap confidence interval for beta difference
n_boot = 5000
beta_diff_boot = []
for _ in range(n_boot):
    idx_e = np.random.choice(earn_mask.sum(), size=earn_mask.sum(), replace=True)
    idx_n = np.random.choice(non_ev_mask.sum(), size=non_ev_mask.sum(), replace=True)

    tw_e = tw50_aligned[earn_mask].values[idx_e]
    ts_e = tsmc_aligned[earn_mask].values[idx_e]
    tw_n = tw50_aligned[non_ev_mask].values[idx_n]
    ts_n = tsmc_aligned[non_ev_mask].values[idx_n]

    b_e = np.cov(tw_e, ts_e)[0,1] / np.var(ts_e) if np.var(ts_e) > 0 else np.nan
    b_n = np.cov(tw_n, ts_n)[0,1] / np.var(ts_n) if np.var(ts_n) > 0 else np.nan

    if not np.isnan(b_e) and not np.isnan(b_n):
        beta_diff_boot.append(b_e - b_n)

beta_diff_boot = np.array(beta_diff_boot)
beta_diff_mean = np.mean(beta_diff_boot)
beta_diff_ci = np.percentile(beta_diff_boot, [2.5, 97.5])
beta_diff_sig = not (beta_diff_ci[0] <= 0 <= beta_diff_ci[1])

print(f"\n  Beta difference (earnings - non-event): {beta_diff_mean:.3f}")
print(f"  95% CI: [{beta_diff_ci[0]:.3f}, {beta_diff_ci[1]:.3f}]")
print(f"  Significant: {'YES' if beta_diff_sig else 'NO'}")

# ============================================================
# Step 7: TSMC |return| on event days
# ============================================================
print("\n[6] TSMC (2330.TW) own event-day analysis...")

tsmc_ret = tsmc['Return'].dropna()
tsmc_abs = tsmc_ret.abs()

tsmc_earn_mask = tsmc_abs.index.isin(earnings_event_set)
tsmc_rev_mask = tsmc_abs.index.isin(revenue_event_set)
tsmc_non_mask = ~tsmc_abs.index.isin(all_tsmc_event_set)

stats_tsmc_earnings = compute_event_stats(
    tsmc_abs[tsmc_earn_mask], tsmc_abs[tsmc_non_mask], "TSMC Earnings (2330.TW)")
stats_tsmc_revenue = compute_event_stats(
    tsmc_abs[tsmc_rev_mask], tsmc_abs[tsmc_non_mask], "TSMC Revenue (2330.TW)")

# ============================================================
# Step 8: Event window plots
# ============================================================
print("\n[7] Generating event window plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
window_range = np.arange(-5, 6)

# Plot 1: Earnings - average |return|
if earn_abs is not None:
    ax = axes[0, 0]
    ax.bar(window_range, earn_abs * 100, color=['#e74c3c' if x == 0 else '#3498db' for x in window_range],
           alpha=0.8, edgecolor='white')
    ax.axhline(y=non_event_abs.mean() * 100, color='gray', linestyle='--', linewidth=1.5,
               label=f'Non-event avg ({non_event_abs.mean()*100:.2f}%)')
    ax.set_title(f'0050.TW |Return| Around TSMC Earnings\n(n={earn_n} events)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Trading Days Relative to Earnings')
    ax.set_ylabel('Average |Return| (%)')
    ax.legend()
    ax.set_xticks(window_range)

# Plot 2: Revenue - average |return|
if rev_abs is not None:
    ax = axes[0, 1]
    ax.bar(window_range, rev_abs * 100, color=['#e74c3c' if x == 0 else '#2ecc71' for x in window_range],
           alpha=0.8, edgecolor='white')
    ax.axhline(y=non_event_abs.mean() * 100, color='gray', linestyle='--', linewidth=1.5,
               label=f'Non-event avg ({non_event_abs.mean()*100:.2f}%)')
    ax.set_title(f'0050.TW |Return| Around TSMC Revenue\n(n={rev_n} events)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Trading Days Relative to Revenue')
    ax.set_ylabel('Average |Return| (%)')
    ax.legend()
    ax.set_xticks(window_range)

# Plot 3: Cumulative average return (CAR)
if earn_ret is not None and rev_ret is not None:
    ax = axes[1, 0]
    earn_car = np.cumsum(earn_ret) * 100
    rev_car = np.cumsum(rev_ret) * 100
    ax.plot(window_range, earn_car, 'r-o', linewidth=2, markersize=5, label=f'Earnings (n={earn_n})')
    ax.plot(window_range, rev_car, 'g-s', linewidth=2, markersize=5, label=f'Revenue (n={rev_n})')
    ax.axvline(x=0, color='gray', linestyle=':', alpha=0.5)
    ax.axhline(y=0, color='gray', linestyle='-', alpha=0.3)
    ax.set_title('Cumulative Average Return (CAR)', fontsize=12, fontweight='bold')
    ax.set_xlabel('Trading Days Relative to Event')
    ax.set_ylabel('CAR (%)')
    ax.legend()
    ax.set_xticks(window_range)

# Plot 4: Earnings vs Revenue comparison bar chart
ax = axes[1, 1]
labels = ['Earnings\n(Quarterly)', 'Revenue\n(Monthly)', 'Non-Event']
means = [stats_earnings['mean_event_abs_ret'] * 100,
         stats_revenue['mean_event_abs_ret'] * 100,
         stats_earnings['mean_non_event_abs_ret'] * 100]
colors = ['#e74c3c', '#2ecc71', '#95a5a6']
bars = ax.bar(labels, means, color=colors, alpha=0.8, edgecolor='white')
# Add value labels
for bar, val in zip(bars, means):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.01,
            f'{val:.2f}%', ha='center', va='bottom', fontweight='bold')
# Add significance markers
if stats_earnings['significant_5pct']:
    ax.text(0, means[0] + 0.06, '***' if stats_earnings['p_value'] < 0.001 else '**' if stats_earnings['p_value'] < 0.01 else '*',
            ha='center', fontsize=14, color='red')
if stats_revenue['significant_5pct']:
    ax.text(1, means[1] + 0.06, '***' if stats_revenue['p_value'] < 0.001 else '**' if stats_revenue['p_value'] < 0.01 else '*',
            ha='center', fontsize=14, color='green')
ax.set_title('0050.TW Average |Return|: Event vs Non-Event', fontsize=12, fontweight='bold')
ax.set_ylabel('Average |Return| (%)')

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, 'k926_event_window.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k926_event_window.png")

# ============================================================
# Step 9: TSMC vs 0050.TW scatter on event days
# ============================================================
fig2, axes2 = plt.subplots(1, 2, figsize=(14, 6))

# Earnings days scatter
ax = axes2[0]
if earn_mask.sum() > 0:
    ax.scatter(tsmc_aligned[earn_mask] * 100, tw50_aligned[earn_mask] * 100,
               c='red', alpha=0.6, s=40, label=f'Earnings (n={earn_mask.sum()})')
ax.scatter(tsmc_aligned[non_ev_mask] * 100, tw50_aligned[non_ev_mask] * 100,
           c='gray', alpha=0.1, s=10, label=f'Non-event (n={non_ev_mask.sum()})')
# Regression lines
x_range = np.linspace(tsmc_aligned.min() * 100, tsmc_aligned.max() * 100, 100)
if not np.isnan(beta_earn):
    ax.plot(x_range, beta_earn * x_range / 100 * 100, 'r-', linewidth=2,
            label=f'Earn beta={beta_earn:.2f}')
if not np.isnan(beta_non):
    ax.plot(x_range, beta_non * x_range / 100 * 100, 'gray', linewidth=1.5, linestyle='--',
            label=f'Non-event beta={beta_non:.2f}')
ax.set_xlabel('TSMC (2330.TW) Return (%)')
ax.set_ylabel('0050.TW Return (%)')
ax.set_title(f'TSMC → 0050.TW: Earnings Days\nbeta={beta_earn:.2f} vs non-event={beta_non:.2f}',
             fontsize=12, fontweight='bold')
ax.legend(fontsize=9)
ax.axhline(y=0, color='gray', alpha=0.3)
ax.axvline(x=0, color='gray', alpha=0.3)

# Event type comparison
ax = axes2[1]
categories = ['All\nDays', 'Earnings\nDays', 'Revenue\nDays', 'Non-Event\nDays']
betas = [beta_all, beta_earn, beta_rev, beta_non]
corrs = [corr_all, corr_earn, corr_rev, corr_non]

x_pos = np.arange(len(categories))
width = 0.35
bars1 = ax.bar(x_pos - width/2, betas, width, label='Beta', color='#3498db', alpha=0.8)
bars2 = ax.bar(x_pos + width/2, corrs, width, label='Correlation', color='#e67e22', alpha=0.8)

for bar, val in zip(bars1, betas):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.01,
            f'{val:.2f}', ha='center', va='bottom', fontsize=9)
for bar, val in zip(bars2, corrs):
    ax.text(bar.get_x() + bar.get_width()/2., bar.get_height() + 0.01,
            f'{val:.2f}', ha='center', va='bottom', fontsize=9)

ax.set_xticks(x_pos)
ax.set_xticklabels(categories)
ax.set_ylabel('Value')
ax.set_title('TSMC → 0050.TW Beta & Correlation\nby Event Type', fontsize=12, fontweight='bold')
ax.legend()

plt.tight_layout()
fig2.savefig(os.path.join(OUTPUT_DIR, 'k926_earnings_vs_revenue.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved: k926_earnings_vs_revenue.png")

# ============================================================
# Step 10: Year-by-year analysis
# ============================================================
print("\n[8] Year-by-year earnings event volatility...")

yearly_results = []
for year in range(2015, 2027):
    year_mask = tw50_ret.index.year == year
    year_ret = tw50_ret[year_mask]
    year_abs = year_ret.abs()

    year_earn_mask = year_ret.index.isin(earnings_event_set)
    year_non_mask = ~year_ret.index.isin(all_tsmc_event_set)

    if year_earn_mask.sum() > 0 and year_non_mask.sum() > 0:
        e_mean = year_abs[year_earn_mask].mean()
        n_mean = year_abs[year_non_mask].mean()
        ratio = e_mean / n_mean if n_mean > 0 else np.nan
        yearly_results.append({
            'year': year,
            'n_earnings_days': int(year_earn_mask.sum()),
            'mean_earn_abs_ret': float(e_mean),
            'mean_non_abs_ret': float(n_mean),
            'ratio': float(ratio),
        })
        print(f"  {year}: earn={e_mean*100:.2f}% vs non={n_mean*100:.2f}% (ratio={ratio:.2f}x), n_earn={year_earn_mask.sum()}")

# ============================================================
# Step 11: Directional analysis — do earnings tend to be positive or negative?
# ============================================================
print("\n[9] Directional analysis of 0050.TW around earnings...")

earn_day0_returns = []
for ed in earnings_trading_days:
    if ed in tw50_ret.index:
        earn_day0_returns.append(tw50_ret.loc[ed])

earn_day0_returns = np.array(earn_day0_returns)
n_positive = np.sum(earn_day0_returns > 0)
n_negative = np.sum(earn_day0_returns < 0)
n_total = len(earn_day0_returns)
pct_positive = n_positive / n_total * 100 if n_total > 0 else 0

# Binomial test: is positive rate significantly different from 50%?
binom_p = stats.binomtest(n_positive, n_total, 0.5).pvalue if n_total > 0 else 1.0

print(f"  Earnings day 0050.TW returns:")
print(f"    Positive: {n_positive}/{n_total} ({pct_positive:.1f}%)")
print(f"    Negative: {n_negative}/{n_total} ({100-pct_positive:.1f}%)")
print(f"    Mean return: {np.mean(earn_day0_returns)*100:.3f}%")
print(f"    Binomial test (vs 50%): p={binom_p:.4f}")

# ============================================================
# Step 12: Pre-event drift analysis
# ============================================================
print("\n[10] Pre-event drift analysis (days -5 to -1)...")

pre_event_returns = []
post_event_returns = []

for ed in earnings_trading_days:
    idx = tw50_ret.index.get_indexer([ed], method='nearest')[0]
    if idx - 5 >= 0 and idx + 5 < len(tw50_ret):
        pre = tw50_ret.iloc[idx-5:idx].sum()  # cumulative pre-event
        post = tw50_ret.iloc[idx:idx+5].sum()  # cumulative post-event (incl day 0)
        pre_event_returns.append(pre)
        post_event_returns.append(post)

pre_event_returns = np.array(pre_event_returns)
post_event_returns = np.array(post_event_returns)

pre_mean = np.mean(pre_event_returns) * 100
post_mean = np.mean(post_event_returns) * 100
pre_t, pre_p = stats.ttest_1samp(pre_event_returns, 0)
post_t, post_p = stats.ttest_1samp(post_event_returns, 0)

print(f"  Pre-event CAR [-5,-1]:  mean={pre_mean:.3f}%, t={pre_t:.2f}, p={pre_p:.4f}")
print(f"  Post-event CAR [0,+4]:  mean={post_mean:.3f}%, t={post_t:.2f}, p={post_p:.4f}")

# ============================================================
# Step 13: Compile Results
# ============================================================
print("\n[11] Compiling results...")

results = {
    'experiment_id': 'K926',
    'title': 'TSMC Earnings/Revenue Announcement Volatility on 0050.TW',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': {
        'etf': '0050.TW (yfinance)',
        'stock': '2330.TW (yfinance)',
        'period': f"{tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')}",
        'n_trading_days': len(tw50),
    },
    'event_counts': {
        'quarterly_earnings': len(earnings_trading_days),
        'monthly_revenue_total': len(revenue_trading_days),
        'monthly_revenue_excl_overlap': len(revenue_only),
    },
    'event_day_analysis': {
        'quarterly_earnings_vs_non_event': stats_earnings,
        'monthly_revenue_vs_non_event': stats_revenue,
        'all_tsmc_events_vs_non_event': stats_all,
    },
    'tsmc_own_event_analysis': {
        'tsmc_earnings': stats_tsmc_earnings,
        'tsmc_revenue': stats_tsmc_revenue,
    },
    'tsmc_to_0050_transmission': {
        'overall_beta': float(beta_all),
        'overall_corr': float(corr_all),
        'earnings_beta': float(beta_earn) if not np.isnan(beta_earn) else None,
        'earnings_corr': float(corr_earn) if not np.isnan(corr_earn) else None,
        'revenue_beta': float(beta_rev) if not np.isnan(beta_rev) else None,
        'revenue_corr': float(corr_rev) if not np.isnan(corr_rev) else None,
        'non_event_beta': float(beta_non) if not np.isnan(beta_non) else None,
        'non_event_corr': float(corr_non) if not np.isnan(corr_non) else None,
        'beta_diff_earnings_vs_non': {
            'mean': float(beta_diff_mean),
            'ci_95': [float(beta_diff_ci[0]), float(beta_diff_ci[1])],
            'significant': bool(beta_diff_sig),
        },
    },
    'directional_analysis': {
        'n_total': int(n_total),
        'n_positive': int(n_positive),
        'n_negative': int(n_negative),
        'pct_positive': float(pct_positive),
        'mean_return_pct': float(np.mean(earn_day0_returns) * 100),
        'binomial_p_value': float(binom_p),
    },
    'pre_post_event_drift': {
        'pre_event_car_mean_pct': float(pre_mean),
        'pre_event_t_stat': float(pre_t),
        'pre_event_p_value': float(pre_p),
        'post_event_car_mean_pct': float(post_mean),
        'post_event_t_stat': float(post_t),
        'post_event_p_value': float(post_p),
    },
    'yearly_analysis': yearly_results,
    'key_findings': '',  # filled below
    'limitations': [
        'Earnings dates are manually compiled; some may differ from actual announcement',
        'Monthly revenue dates approximated as 10th (may vary by 1-2 days)',
        'Event window overlap may occur between consecutive months',
        '0050.TW weight of TSMC has changed over time (from ~25% to ~50%+)',
        'No control for concurrent macro events (e.g., Fed decisions, US earnings)',
    ],
    'references': [
        'MacKinlay (1997) Event studies in economics and finance, JEL',
        'Patell & Wolfson (1984) The intraday speed of adjustment',
    ],
}

# Generate key findings summary
earn_ratio = stats_earnings['ratio']
rev_ratio = stats_revenue['ratio']
earn_sig = 'significant' if stats_earnings['significant_5pct'] else 'not significant'
rev_sig = 'significant' if stats_revenue['significant_5pct'] else 'not significant'

key_findings = (
    f"TSMC earnings/revenue event study on 0050.TW ({tw50.index[0].strftime('%Y')}-{tw50.index[-1].strftime('%Y')}, "
    f"{len(earnings_trading_days)} earnings + {len(revenue_only)} revenue events). "
    f"Quarterly earnings: |return| ratio {earn_ratio:.2f}x vs non-event ({earn_sig}, "
    f"t={stats_earnings['t_stat']:.2f}, p={stats_earnings['p_value']:.4f}, "
    f"Cohen's d={stats_earnings['cohens_d']:.3f}). "
    f"Monthly revenue: ratio {rev_ratio:.2f}x ({rev_sig}, "
    f"t={stats_revenue['t_stat']:.2f}, p={stats_revenue['p_value']:.4f}). "
    f"TSMC→0050 beta: earnings days {beta_earn:.2f} vs non-event {beta_non:.2f} "
    f"(diff {'significant' if beta_diff_sig else 'NS'}, 95% CI [{beta_diff_ci[0]:.2f}, {beta_diff_ci[1]:.2f}]). "
    f"Directional: {pct_positive:.0f}% positive on earnings days "
    f"(binomial p={binom_p:.3f}). "
    f"Pre-event CAR [-5,-1]: {pre_mean:.3f}% (p={pre_p:.3f}), "
    f"post-event CAR [0,+4]: {post_mean:.3f}% (p={post_p:.3f}). "
    f"TSMC itself: earnings |return| {stats_tsmc_earnings['ratio']:.2f}x "
    f"({'significant' if stats_tsmc_earnings['significant_5pct'] else 'NS'})."
)

results['key_findings'] = key_findings

# Save results
results_path = os.path.join(OUTPUT_DIR, 'k926_tsmc_earnings_vol_results.json')
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\n  Saved: k926_tsmc_earnings_vol_results.json")

# ============================================================
# Final Summary
# ============================================================
print("\n" + "=" * 70)
print("K926 RESULTS SUMMARY")
print("=" * 70)
print(f"\nQuarterly Earnings Impact on 0050.TW:")
print(f"  |return| ratio: {earn_ratio:.2f}x ({earn_sig})")
print(f"  t={stats_earnings['t_stat']:.3f}, p={stats_earnings['p_value']:.4f}")
print(f"\nMonthly Revenue Impact on 0050.TW:")
print(f"  |return| ratio: {rev_ratio:.2f}x ({rev_sig})")
print(f"  t={stats_revenue['t_stat']:.3f}, p={stats_revenue['p_value']:.4f}")
print(f"\nTSMC → 0050.TW Transmission:")
print(f"  Earnings beta: {beta_earn:.3f} vs non-event: {beta_non:.3f}")
print(f"  Beta difference significant: {'YES' if beta_diff_sig else 'NO'}")
print(f"\nKey Finding: {key_findings[:200]}...")
print("=" * 70)
