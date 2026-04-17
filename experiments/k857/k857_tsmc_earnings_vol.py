"""
K857: TSMC Earnings Announcement Volatility — 2026 Update with Tariff Context
===============================================================================
[提出: 用戶, 執行: Claude]

研究問題:
1. TSMC 月營收公告日對 0050.TW 波動率的影響（2015-2026 更新）
2. VIX regime interaction: 高 VIX 環境下公告日波動率是否更大？
3. 公告前後的報酬率型態（event drift）
4. 2026/04/10 特殊情境預測（VIX > 30 + 關稅）

數據來源: yfinance (0050.TW, 2330.TW, ^VIX), 2015-01 ~ 2026-04
TSMC revenue dates: 每月10日（或下一交易日），程式產生，共 ~135 事件

文獻基礎:
- Patell & Wolfson (1984) "Intraday Speed of Adjustment" JFE
- Dubinsky & Johannes (2006) "Earnings Announcements and Equity Options" Columbia WP
- K617: 原始 TSMC event study (134 事件，vol 比非事件日高)
- K847/K848: 台灣市場隔夜波動與全球化

Error Log 注意:
- 0050.TW: MUST use clean_tw50_data
- Sanity check: compute actual values, never hard-code
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import warnings
import sys
import os

# Add project root to path for volpred imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

print("=" * 70)
print("K857: TSMC Earnings Announcement Volatility — 2026 Update")
print("=" * 70)

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n[1] Downloading data...")

# 0050.TW with proper split cleaning
etf_raw = yf.download('0050.TW', start='2015-01-01', end='2026-12-31', progress=False)
if isinstance(etf_raw.columns, pd.MultiIndex):
    etf_raw.columns = etf_raw.columns.get_level_values(0)
etf_prices = etf_raw['Close'].squeeze()
etf_clean_prices, etf_clean_returns = clean_tw50_data(etf_prices)

etf = pd.DataFrame({
    'Close': etf_clean_prices,
    'Return': etf_clean_returns,
    'AbsReturn': etf_clean_returns.abs(),
    'SqReturn': etf_clean_returns ** 2,
}).dropna()

# 2330.TW (TSMC)
tsmc_raw = yf.download('2330.TW', start='2015-01-01', end='2026-12-31', progress=False)
if isinstance(tsmc_raw.columns, pd.MultiIndex):
    tsmc_raw.columns = tsmc_raw.columns.get_level_values(0)
tsmc = pd.DataFrame({'Close': tsmc_raw['Close'].squeeze()})
tsmc['Return'] = tsmc['Close'].pct_change()
tsmc['AbsReturn'] = tsmc['Return'].abs()
tsmc = tsmc.dropna()

# VIX
vix_raw = yf.download('^VIX', start='2015-01-01', end='2026-12-31', progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = pd.DataFrame({'VIX': vix_raw['Close'].squeeze()}).dropna()

print(f"  0050.TW: {etf.index[0].strftime('%Y-%m-%d')} to {etf.index[-1].strftime('%Y-%m-%d')} ({len(etf)} days)")
print(f"  2330.TW: {tsmc.index[0].strftime('%Y-%m-%d')} to {tsmc.index[-1].strftime('%Y-%m-%d')} ({len(tsmc)} days)")
print(f"  VIX:     {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')} ({len(vix)} days)")

# Descriptive stats
print(f"\n  0050.TW mean daily |ret|: {etf['AbsReturn'].mean()*100:.4f}%")
print(f"  0050.TW std  daily |ret|: {etf['AbsReturn'].std()*100:.4f}%")
print(f"  2330.TW mean daily |ret|: {tsmc['AbsReturn'].mean()*100:.4f}%")
print(f"  VIX mean: {vix['VIX'].mean():.2f}, current (last): {vix['VIX'].iloc[-1]:.2f}")

# =============================================================================
# 2. GENERATE TSMC REVENUE ANNOUNCEMENT DATES
# =============================================================================
print("\n[2] Generating TSMC revenue announcement dates...")

# Common trading days across all datasets
common_days = sorted(set(etf.index.normalize()) & set(tsmc.index.normalize()))
trading_days_idx = pd.DatetimeIndex(common_days)

def next_trading_day(date, tdi):
    """Find next trading day on or after date."""
    date = pd.Timestamp(date).normalize()
    mask = tdi >= date
    if mask.any():
        return tdi[mask][0]
    return None

# Monthly revenue announcement dates (10th of each month)
revenue_dates = []
for year in range(2015, 2027):
    for month in range(1, 13):
        try:
            target = pd.Timestamp(f"{year}-{month:02d}-10")
            td = next_trading_day(target, trading_days_idx)
            if td is not None and td <= etf.index[-1]:
                revenue_dates.append(td)
        except:
            pass

print(f"  Total revenue announcement dates: {len(revenue_dates)}")
print(f"  First: {revenue_dates[0].strftime('%Y-%m-%d')}")
print(f"  Last:  {revenue_dates[-1].strftime('%Y-%m-%d')}")

# =============================================================================
# 3. ASSIGN VIX TO EACH EVENT DATE
# =============================================================================
print("\n[3] Matching VIX levels to event dates...")

# For each event date, find the most recent VIX reading
# (VIX is US market — use previous day's close for Taiwan dates)
def get_vix_for_date(date, vix_df):
    """Get VIX level for a Taiwan trading day (use prev US close)."""
    date = pd.Timestamp(date).normalize()
    # Look back up to 5 days for VIX reading
    for offset in range(0, 6):
        check = date - pd.Timedelta(days=offset)
        if check in vix_df.index:
            return vix_df.loc[check, 'VIX']
    return np.nan

event_vix = {}
for d in revenue_dates:
    event_vix[d] = get_vix_for_date(d, vix)

vix_values = [event_vix[d] for d in revenue_dates if not np.isnan(event_vix.get(d, np.nan))]
print(f"  Events with VIX match: {len(vix_values)}/{len(revenue_dates)}")
print(f"  VIX at events — mean: {np.mean(vix_values):.2f}, median: {np.median(vix_values):.2f}")
print(f"  VIX at events — min: {np.min(vix_values):.2f}, max: {np.max(vix_values):.2f}")

# Define VIX regimes
VIX_LOW = 16
VIX_MED = 25
# Low: VIX < 16, Medium: 16-25, High: > 25

# =============================================================================
# 4. EVENT STUDY: VOL IMPACT + VIX REGIME INTERACTION
# =============================================================================
print("\n[4] Event study: vol impact by VIX regime...")

WINDOW = 3  # [-3, +3] day window

event_records = []
for event_date in revenue_dates:
    if event_date not in etf.index or event_date not in tsmc.index:
        continue

    etf_idx = etf.index.get_loc(event_date)
    tsmc_idx = tsmc.index.get_loc(event_date)

    if etf_idx < WINDOW or etf_idx >= len(etf) - WINDOW:
        continue
    if tsmc_idx < WINDOW or tsmc_idx >= len(tsmc) - WINDOW:
        continue

    v = event_vix.get(event_date, np.nan)
    if np.isnan(v):
        continue

    # Classify VIX regime
    if v < VIX_LOW:
        regime = 'low'
    elif v < VIX_MED:
        regime = 'medium'
    else:
        regime = 'high'

    # Extract window data
    etf_window_abs = [etf['AbsReturn'].iloc[etf_idx + i] for i in range(-WINDOW, WINDOW + 1)]
    tsmc_window_abs = [tsmc['AbsReturn'].iloc[tsmc_idx + i] for i in range(-WINDOW, WINDOW + 1)]
    etf_window_ret = [etf['Return'].iloc[etf_idx + i] for i in range(-WINDOW, WINDOW + 1)]
    tsmc_window_ret = [tsmc['Return'].iloc[tsmc_idx + i] for i in range(-WINDOW, WINDOW + 1)]

    # Pre-event vol (mean of days -3 to -1)
    pre_vol_etf = np.mean(etf_window_abs[:WINDOW])
    # Event day vol (day 0)
    event_vol_etf = etf_window_abs[WINDOW]
    # Post-event vol (mean of days +1 to +3)
    post_vol_etf = np.mean(etf_window_abs[WINDOW+1:])

    pre_vol_tsmc = np.mean(tsmc_window_abs[:WINDOW])
    event_vol_tsmc = tsmc_window_abs[WINDOW]
    post_vol_tsmc = np.mean(tsmc_window_abs[WINDOW+1:])

    # TSMC revenue surprise proxy: compare current month vs 3-month moving average
    # We use TSMC stock return on event day as a proxy for surprise direction
    event_ret_tsmc = tsmc_window_ret[WINDOW]
    surprise_dir = 'positive' if event_ret_tsmc > 0 else 'negative'

    event_records.append({
        'date': event_date,
        'vix': v,
        'regime': regime,
        'pre_vol_etf': pre_vol_etf,
        'event_vol_etf': event_vol_etf,
        'post_vol_etf': post_vol_etf,
        'pre_vol_tsmc': pre_vol_tsmc,
        'event_vol_tsmc': event_vol_tsmc,
        'post_vol_tsmc': post_vol_tsmc,
        'event_ret_etf': etf_window_ret[WINDOW],
        'event_ret_tsmc': event_ret_tsmc,
        'surprise_dir': surprise_dir,
        # Full window for cumulative return analysis
        'etf_window_ret': etf_window_ret,
        'tsmc_window_ret': tsmc_window_ret,
        'etf_window_abs': etf_window_abs,
    })

events_df = pd.DataFrame(event_records)
print(f"  Valid events with full data: {len(events_df)}")
print(f"  VIX regime distribution:")
for r in ['low', 'medium', 'high']:
    n = (events_df['regime'] == r).sum()
    print(f"    {r:>7s}: {n} events ({n/len(events_df)*100:.1f}%)")

# --- Non-event days baseline ---
event_dates_set = set([d.normalize() for d in events_df['date']])
# Exclude event day +/- WINDOW from baseline
excluded = set()
for d in event_dates_set:
    for offset in range(-WINDOW, WINDOW + 1):
        excluded.add(d + pd.Timedelta(days=offset))
non_event_mask = ~etf.index.normalize().isin(excluded)
non_event_vol = etf.loc[non_event_mask, 'AbsReturn'].mean()
non_event_vol_std = etf.loc[non_event_mask, 'AbsReturn'].std()
n_non_event = non_event_mask.sum()

print(f"\n  Non-event days: {n_non_event}")
print(f"  Non-event mean |ret|: {non_event_vol*100:.4f}%")

# --- Overall event day vs non-event day ---
event_day_vol = events_df['event_vol_etf'].mean()
event_day_vol_std = events_df['event_vol_etf'].std()

print(f"\n  Event day mean |ret|: {event_day_vol*100:.4f}%")
print(f"  Vol ratio (event/non-event): {event_day_vol/non_event_vol:.3f}x")

# t-test: event day vol vs non-event vol
t_stat, p_val = stats.ttest_ind(
    events_df['event_vol_etf'].values,
    etf.loc[non_event_mask, 'AbsReturn'].values,
    equal_var=False
)
print(f"  Welch t-test: t={t_stat:.3f}, p={p_val:.4f}")

# =============================================================================
# 5. VIX REGIME INTERACTION ANALYSIS
# =============================================================================
print("\n[5] VIX regime interaction...")

regime_results = {}
for regime in ['low', 'medium', 'high']:
    mask = events_df['regime'] == regime
    subset = events_df[mask]

    if len(subset) < 5:
        print(f"  {regime}: only {len(subset)} events, skipping")
        continue

    mean_vol = subset['event_vol_etf'].mean()
    std_vol = subset['event_vol_etf'].std()
    mean_pre = subset['pre_vol_etf'].mean()
    mean_post = subset['post_vol_etf'].mean()

    # Ratio: event day vol / pre-event vol (this removes baseline vol level)
    vol_ratios = subset['event_vol_etf'] / subset['pre_vol_etf'].replace(0, np.nan)
    mean_ratio = vol_ratios.mean()

    # Also compute TSMC amplification: TSMC vol / ETF vol on event day
    amp = (subset['event_vol_tsmc'] / subset['event_vol_etf'].replace(0, np.nan)).mean()

    regime_results[regime] = {
        'n_events': int(len(subset)),
        'mean_event_vol_pct': round(mean_vol * 100, 4),
        'mean_pre_vol_pct': round(mean_pre * 100, 4),
        'mean_post_vol_pct': round(mean_post * 100, 4),
        'vol_ratio_event_vs_pre': round(mean_ratio, 3),
        'tsmc_amplification': round(amp, 3),
        'mean_vix': round(subset['vix'].mean(), 2),
    }

    print(f"\n  VIX regime: {regime.upper()} (n={len(subset)}, mean VIX={subset['vix'].mean():.1f})")
    print(f"    Pre-event vol:   {mean_pre*100:.4f}%")
    print(f"    Event-day vol:   {mean_vol*100:.4f}%")
    print(f"    Post-event vol:  {mean_post*100:.4f}%")
    print(f"    Event/Pre ratio: {mean_ratio:.3f}x")
    print(f"    TSMC amp factor: {amp:.3f}x")

# Test: high-VIX event vol vs low-VIX event vol
if 'high' in regime_results and 'low' in regime_results:
    high_vols = events_df[events_df['regime'] == 'high']['event_vol_etf']
    low_vols = events_df[events_df['regime'] == 'low']['event_vol_etf']
    t_hl, p_hl = stats.ttest_ind(high_vols, low_vols, equal_var=False)
    print(f"\n  High vs Low VIX event vol: t={t_hl:.3f}, p={p_hl:.4f}")
    regime_interaction_t = round(t_hl, 3)
    regime_interaction_p = round(p_hl, 4)
else:
    regime_interaction_t = None
    regime_interaction_p = None

# =============================================================================
# 6. CUMULATIVE RETURN PATTERN AROUND EVENTS
# =============================================================================
print("\n[6] Cumulative return pattern around events...")

# Average cumulative return in [-3, +3] window
n_days = 2 * WINDOW + 1
cum_ret_matrix = np.zeros((len(events_df), n_days))
for i, row in events_df.iterrows():
    rets = np.array(row['etf_window_ret'])
    cum_ret_matrix[i] = np.cumsum(rets)

avg_cum_ret = cum_ret_matrix.mean(axis=0) * 100  # in percent
std_cum_ret = cum_ret_matrix.std(axis=0) * 100
day_labels = list(range(-WINDOW, WINDOW + 1))

print(f"  Average cumulative return pattern (%):")
for j, label in enumerate(day_labels):
    print(f"    Day {label:+d}: {avg_cum_ret[j]:+.4f}% (std {std_cum_ret[j]:.4f}%)")

# By regime
cum_ret_by_regime = {}
for regime in ['low', 'medium', 'high']:
    mask = events_df['regime'] == regime
    if mask.sum() < 5:
        continue
    subset_matrix = cum_ret_matrix[mask.values]
    avg = subset_matrix.mean(axis=0) * 100
    cum_ret_by_regime[regime] = {
        'n': int(mask.sum()),
        'cum_ret_day_labels': day_labels,
        'cum_ret_pct': [round(x, 4) for x in avg.tolist()],
    }
    print(f"\n  {regime.upper()} VIX regime (n={mask.sum()}):")
    for j, label in enumerate(day_labels):
        print(f"    Day {label:+d}: {avg[j]:+.4f}%")

# =============================================================================
# 7. SURPRISE DIRECTION ANALYSIS
# =============================================================================
print("\n[7] Surprise direction analysis (TSMC return on event day as proxy)...")

for direction in ['positive', 'negative']:
    mask = events_df['surprise_dir'] == direction
    subset = events_df[mask]
    mean_ret = subset['event_ret_etf'].mean() * 100
    mean_vol = subset['event_vol_etf'].mean() * 100
    print(f"  {direction.upper()} surprise (n={len(subset)}):")
    print(f"    0050.TW mean return: {mean_ret:+.4f}%")
    print(f"    0050.TW mean |ret|:  {mean_vol:.4f}%")

# Is negative surprise vol > positive surprise vol?
pos_vols = events_df[events_df['surprise_dir'] == 'positive']['event_vol_etf']
neg_vols = events_df[events_df['surprise_dir'] == 'negative']['event_vol_etf']
t_pn, p_pn = stats.ttest_ind(neg_vols, pos_vols, equal_var=False)
print(f"\n  Neg vs Pos surprise vol: t={t_pn:.3f}, p={p_pn:.4f}")
neg_vs_pos_asymmetry = round(neg_vols.mean() / pos_vols.mean(), 3)
print(f"  Asymmetry ratio (neg/pos): {neg_vs_pos_asymmetry}")

# =============================================================================
# 8. TSMC AMPLIFICATION FACTOR
# =============================================================================
print("\n[8] TSMC amplification factor (2330.TW / 0050.TW)...")

amp_overall = (events_df['event_vol_tsmc'] / events_df['event_vol_etf'].replace(0, np.nan)).dropna()
print(f"  Mean amplification: {amp_overall.mean():.3f}x")
print(f"  Median amplification: {amp_overall.median():.3f}x")
print(f"  Std: {amp_overall.std():.3f}")

# =============================================================================
# 9. BOOTSTRAP CI FOR KEY METRICS
# =============================================================================
print("\n[9] Bootstrap confidence intervals (10000 reps)...")

np.random.seed(42)
N_BOOT = 10000

def bootstrap_ci(data, n_boot=N_BOOT, ci=0.95):
    """Bootstrap confidence interval for the mean."""
    data = np.array(data)
    means = np.array([np.mean(np.random.choice(data, size=len(data), replace=True)) for _ in range(n_boot)])
    alpha = (1 - ci) / 2
    return np.percentile(means, [alpha * 100, (1 - alpha) * 100])

# Event vol ratio
vol_ratios_all = (events_df['event_vol_etf'] / non_event_vol).values
ci_vol_ratio = bootstrap_ci(vol_ratios_all)
print(f"  Event/Non-event vol ratio: {vol_ratios_all.mean():.3f} [{ci_vol_ratio[0]:.3f}, {ci_vol_ratio[1]:.3f}]")

# High-VIX event vol
if (events_df['regime'] == 'high').sum() >= 5:
    high_vols_arr = events_df[events_df['regime'] == 'high']['event_vol_etf'].values
    ci_high = bootstrap_ci(high_vols_arr * 100)
    print(f"  High-VIX event vol (%): {high_vols_arr.mean()*100:.4f} [{ci_high[0]:.4f}, {ci_high[1]:.4f}]")

# Amplification
ci_amp = bootstrap_ci(amp_overall.values)
print(f"  TSMC amplification: {amp_overall.mean():.3f} [{ci_amp[0]:.3f}, {ci_amp[1]:.3f}]")

# =============================================================================
# 10. YEAR-OVER-YEAR TREND
# =============================================================================
print("\n[10] Year-over-year trend in event-day vol...")

events_df['year'] = events_df['date'].dt.year
yearly_stats = events_df.groupby('year').agg(
    n_events=('event_vol_etf', 'count'),
    mean_event_vol=('event_vol_etf', 'mean'),
    mean_vix=('vix', 'mean'),
).reset_index()

yearly_trend = {}
for _, row in yearly_stats.iterrows():
    print(f"  {int(row['year'])}: n={int(row['n_events'])}, event |ret|={row['mean_event_vol']*100:.4f}%, VIX={row['mean_vix']:.1f}")
    yearly_trend[int(row['year'])] = {
        'n_events': int(row['n_events']),
        'mean_event_vol_pct': round(row['mean_event_vol'] * 100, 4),
        'mean_vix': round(row['mean_vix'], 1),
    }

# =============================================================================
# 11. RECENT HIGH-VIX EVENTS (for 2026/04/10 context)
# =============================================================================
print("\n[11] Recent high-VIX TSMC event days (context for April 10)...")

# Find events with VIX >= 25 (similar to current)
high_vix_events = events_df[events_df['vix'] >= 25].sort_values('date', ascending=False)
print(f"  Events with VIX >= 25: {len(high_vix_events)}")
if len(high_vix_events) > 0:
    for _, row in high_vix_events.head(10).iterrows():
        print(f"    {row['date'].strftime('%Y-%m-%d')}: VIX={row['vix']:.1f}, "
              f"0050 |ret|={row['event_vol_etf']*100:.3f}%, "
              f"TSMC |ret|={row['event_vol_tsmc']*100:.3f}%, "
              f"0050 ret={row['event_ret_etf']*100:+.3f}%")

# Events with VIX >= 30 (very close to current)
very_high = events_df[events_df['vix'] >= 30].sort_values('date', ascending=False)
print(f"\n  Events with VIX >= 30: {len(very_high)}")
if len(very_high) > 0:
    for _, row in very_high.iterrows():
        print(f"    {row['date'].strftime('%Y-%m-%d')}: VIX={row['vix']:.1f}, "
              f"0050 |ret|={row['event_vol_etf']*100:.3f}%, "
              f"TSMC |ret|={row['event_vol_tsmc']*100:.3f}%, "
              f"0050 ret={row['event_ret_etf']*100:+.3f}%")

# =============================================================================
# 12. PREDICTION FOR APRIL 10, 2026
# =============================================================================
print("\n[12] Prediction for April 10, 2026 (VIX > 30 + tariff context)...")

# Use high-VIX regime statistics for prediction
current_vix = vix['VIX'].iloc[-1]
print(f"  Current VIX (last available): {current_vix:.2f}")

if 'high' in regime_results:
    high_stats = regime_results['high']
    print(f"\n  Based on HIGH VIX regime events (n={high_stats['n_events']}):")
    print(f"    Expected 0050.TW |ret| on event day: {high_stats['mean_event_vol_pct']:.4f}%")
    print(f"    Pre-event vol buildup:  {high_stats['mean_pre_vol_pct']:.4f}%")
    print(f"    Post-event vol:         {high_stats['mean_post_vol_pct']:.4f}%")
    print(f"    Vol ratio (event/pre):  {high_stats['vol_ratio_event_vs_pre']}x")

    # Compare with unconditional
    unconditional_vol = event_day_vol * 100
    print(f"\n  Comparison:")
    print(f"    Unconditional event vol: {unconditional_vol:.4f}%")
    print(f"    High-VIX event vol:      {high_stats['mean_event_vol_pct']:.4f}%")
    print(f"    Elevated by: {(high_stats['mean_event_vol_pct']/unconditional_vol - 1)*100:.1f}%")

# Check if VIX > 30 events have even higher vol
if len(very_high) >= 3:
    very_high_vol = very_high['event_vol_etf'].mean() * 100
    print(f"\n  VIX >= 30 events (n={len(very_high)}):")
    print(f"    Mean 0050.TW |ret|: {very_high_vol:.4f}%")
    print(f"    This is the most relevant comparison for April 10")

# =============================================================================
# 13. FULL WINDOW VOL PROFILE (heatmap-style)
# =============================================================================
print("\n[13] Full window vol profile by regime...")

vol_profile_by_regime = {}
for regime in ['low', 'medium', 'high']:
    mask = events_df['regime'] == regime
    if mask.sum() < 5:
        continue

    subset = events_df[mask]
    window_vols = np.array(subset['etf_window_abs'].tolist())
    avg_vols = window_vols.mean(axis=0) * 100

    vol_profile_by_regime[regime] = {
        'day_labels': day_labels,
        'avg_vol_pct': [round(x, 4) for x in avg_vols.tolist()],
    }

    print(f"\n  {regime.upper()} VIX regime vol profile (%):")
    for j, label in enumerate(day_labels):
        bar = '#' * int(avg_vols[j] / 0.1)
        marker = ' <-- EVENT' if label == 0 else ''
        print(f"    Day {label:+d}: {avg_vols[j]:.4f}% {bar}{marker}")

# =============================================================================
# 14. COMPILE RESULTS
# =============================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

summary = {
    'total_events': len(events_df),
    'event_vol_pct': round(event_day_vol * 100, 4),
    'non_event_vol_pct': round(non_event_vol * 100, 4),
    'vol_ratio': round(event_day_vol / non_event_vol, 3),
    'vol_ratio_ci_95': [round(ci_vol_ratio[0], 3), round(ci_vol_ratio[1], 3)],
    't_stat_event_vs_nonevent': round(t_stat, 3),
    'p_val_event_vs_nonevent': round(p_val, 4),
    'regime_interaction_t': regime_interaction_t,
    'regime_interaction_p': regime_interaction_p,
    'tsmc_amplification': round(amp_overall.mean(), 3),
    'tsmc_amplification_ci_95': [round(ci_amp[0], 3), round(ci_amp[1], 3)],
    'neg_vs_pos_surprise_asymmetry': neg_vs_pos_asymmetry,
}

print(f"\n  1. TSMC revenue day vol impact:")
print(f"     Event |ret|: {summary['event_vol_pct']:.4f}% vs Non-event: {summary['non_event_vol_pct']:.4f}%")
print(f"     Vol ratio: {summary['vol_ratio']}x [95% CI: {summary['vol_ratio_ci_95']}]")
print(f"     t={summary['t_stat_event_vs_nonevent']}, p={summary['p_val_event_vs_nonevent']}")

print(f"\n  2. VIX regime interaction:")
if regime_interaction_t is not None:
    print(f"     High vs Low VIX: t={regime_interaction_t}, p={regime_interaction_p}")
for r in ['low', 'medium', 'high']:
    if r in regime_results:
        rr = regime_results[r]
        print(f"     {r.upper()}: event vol={rr['mean_event_vol_pct']:.4f}%, ratio={rr['vol_ratio_event_vs_pre']}x")

print(f"\n  3. TSMC amplification: {summary['tsmc_amplification']}x [{summary['tsmc_amplification_ci_95']}]")
print(f"\n  4. Neg/Pos surprise asymmetry: {summary['neg_vs_pos_surprise_asymmetry']}x")

print(f"\n  5. April 10 prediction (VIX ~{current_vix:.0f}):")
if 'high' in regime_results:
    print(f"     Expected 0050.TW |ret|: ~{regime_results['high']['mean_event_vol_pct']:.2f}%")
    if len(very_high) >= 3:
        print(f"     VIX>=30 historical: ~{very_high['event_vol_etf'].mean()*100:.2f}%")
    print(f"     Normal non-event: ~{summary['non_event_vol_pct']:.2f}%")

# =============================================================================
# 15. SAVE RESULTS JSON
# =============================================================================
results = {
    'experiment_id': 'k857',
    'title': 'TSMC Earnings Vol 2026 Update — VIX Regime Interaction',
    'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance (0050.TW, 2330.TW, ^VIX)',
    'period': '2015-01 to 2026-04',
    'methodology': 'Event study with VIX regime interaction, bootstrap CI',
    'references': [
        'K617: Original TSMC event study (134 events)',
        'Patell & Wolfson (1984) JFE',
        'Dubinsky & Johannes (2006) Columbia WP',
    ],
    'summary': summary,
    'regime_results': regime_results,
    'yearly_trend': yearly_trend,
    'cumulative_return_pattern': {
        'overall': {
            'day_labels': day_labels,
            'avg_cum_ret_pct': [round(x, 4) for x in avg_cum_ret.tolist()],
        },
        'by_regime': cum_ret_by_regime,
    },
    'vol_profile_by_regime': vol_profile_by_regime,
    'surprise_analysis': {
        'positive': {
            'n': int((events_df['surprise_dir'] == 'positive').sum()),
            'mean_ret_pct': round(events_df[events_df['surprise_dir'] == 'positive']['event_ret_etf'].mean() * 100, 4),
            'mean_vol_pct': round(events_df[events_df['surprise_dir'] == 'positive']['event_vol_etf'].mean() * 100, 4),
        },
        'negative': {
            'n': int((events_df['surprise_dir'] == 'negative').sum()),
            'mean_ret_pct': round(events_df[events_df['surprise_dir'] == 'negative']['event_ret_etf'].mean() * 100, 4),
            'mean_vol_pct': round(events_df[events_df['surprise_dir'] == 'negative']['event_vol_etf'].mean() * 100, 4),
        },
        'neg_vs_pos_vol_t': round(t_pn, 3),
        'neg_vs_pos_vol_p': round(p_pn, 4),
    },
    'april_10_prediction': {
        'current_vix': round(float(current_vix), 2),
        'expected_event_vol_pct': round(regime_results.get('high', {}).get('mean_event_vol_pct', 0), 4),
        'non_event_baseline_pct': round(non_event_vol * 100, 4),
        'n_historical_vix_ge_30': int(len(very_high)),
        'historical_vix_ge_30_mean_vol_pct': round(very_high['event_vol_etf'].mean() * 100, 4) if len(very_high) > 0 else None,
    },
    'high_vix_recent_events': [
        {
            'date': row['date'].strftime('%Y-%m-%d'),
            'vix': round(row['vix'], 1),
            'etf_abs_ret_pct': round(row['event_vol_etf'] * 100, 3),
            'tsmc_abs_ret_pct': round(row['event_vol_tsmc'] * 100, 3),
            'etf_ret_pct': round(row['event_ret_etf'] * 100, 3),
        }
        for _, row in high_vix_events.head(15).iterrows()
    ],
}

output_path = os.path.join(os.path.dirname(__file__), 'k857_results.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to: {output_path}")
print(f"\n{'='*70}")
print("K857 COMPLETE")
print(f"{'='*70}")
