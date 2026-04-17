"""
K617: TSMC Revenue/Earnings Event Study — 0050.TW Volatility Impact
====================================================================
[提出: 用戶, 執行: Claude]

研究問題:
1. TSMC 月營收公告日（每月10日前後）對 0050.TW vol 的影響
2. TSMC 季度法說會（1/4/7/10月~15日）vs 月營收的影響差異
3. TSMC 個股 vs 0050.TW 反應的放大倍數
4. 公告前後波動率模式（pre-event vol buildup? post-event vol crush?）
5. 營收好壞（beat vs miss）對波動率的差異效果

數據來源: yfinance (0050.TW, 2330.TW), 2015-2026
TSMC revenue dates: 每月10日（或下一個交易日），程式產生
TSMC earnings dates: 每季法說（1/4/7/10月~15日），程式產生

文獻基礎:
- Patell & Wolfson (1984) "The Intraday Speed of Adjustment of Stock Prices to Earnings and Dividend Announcements" JFE
- Dubinsky & Johannes (2006) "Earnings Announcements and Equity Options" Columbia WP
- Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?" RFS
- K512: Taiwan ex-dividend vol event study (post-div vol +32-69%)
- K513: Macro event vol study (FOMC +28%, NFP/CPI null)
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

print("=" * 70)
print("K617: TSMC Revenue/Earnings Event Study")
print("=" * 70)

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n[1] Downloading 0050.TW and 2330.TW data...")
etf = yf.download('0050.TW', start='2015-01-01', end='2026-12-31', progress=False)
tsmc = yf.download('2330.TW', start='2015-01-01', end='2026-12-31', progress=False)

# Flatten multi-index if present
if isinstance(etf.columns, pd.MultiIndex):
    etf.columns = etf.columns.get_level_values(0)
if isinstance(tsmc.columns, pd.MultiIndex):
    tsmc.columns = tsmc.columns.get_level_values(0)

etf['Return'] = etf['Close'].pct_change()
etf['AbsReturn'] = etf['Return'].abs()
etf['LogReturn'] = np.log(etf['Close'] / etf['Close'].shift(1))
etf['AbsLogReturn'] = etf['LogReturn'].abs()

tsmc['Return'] = tsmc['Close'].pct_change()
tsmc['AbsReturn'] = tsmc['Return'].abs()
tsmc['LogReturn'] = np.log(tsmc['Close'] / tsmc['Close'].shift(1))
tsmc['AbsLogReturn'] = tsmc['LogReturn'].abs()

etf = etf.dropna(subset=['Return'])
tsmc = tsmc.dropna(subset=['Return'])

print(f"  0050.TW: {etf.index[0].strftime('%Y-%m-%d')} to {etf.index[-1].strftime('%Y-%m-%d')}")
print(f"  0050.TW trading days: {len(etf)}")
print(f"  2330.TW: {tsmc.index[0].strftime('%Y-%m-%d')} to {tsmc.index[-1].strftime('%Y-%m-%d')}")
print(f"  2330.TW trading days: {len(tsmc)}")

# Descriptive stats
print(f"\n  0050.TW mean |ret|: {etf['AbsReturn'].mean()*100:.4f}%")
print(f"  0050.TW std  |ret|: {etf['AbsReturn'].std()*100:.4f}%")
print(f"  2330.TW mean |ret|: {tsmc['AbsReturn'].mean()*100:.4f}%")
print(f"  2330.TW std  |ret|: {tsmc['AbsReturn'].std()*100:.4f}%")

# =============================================================================
# 2. GENERATE TSMC EVENT DATES
# =============================================================================
print("\n[2] Generating TSMC event dates...")

trading_days_etf = set(etf.index.normalize())
trading_days_tsmc = set(tsmc.index.normalize())
# Common trading days
trading_days = sorted(trading_days_etf & trading_days_tsmc)
trading_days_list = pd.DatetimeIndex(trading_days)

def next_trading_day(date, trading_days_idx):
    """Find the next trading day on or after the given date."""
    date = pd.Timestamp(date).normalize()
    mask = trading_days_idx >= date
    if mask.any():
        return trading_days_idx[mask][0]
    return None

# --- Monthly Revenue Announcement Dates ---
# TSMC reports monthly revenue on the 10th of each month (or next trading day)
# Revenue for month M is reported around the 10th of month M+1
revenue_dates = []
for year in range(2015, 2027):
    for month in range(1, 13):
        try:
            target = pd.Timestamp(f"{year}-{month:02d}-10")
            td = next_trading_day(target, trading_days_list)
            if td is not None and td <= etf.index[-1]:
                revenue_dates.append(td)
        except:
            pass

print(f"  Monthly revenue announcement dates: {len(revenue_dates)}")
print(f"  First: {revenue_dates[0].strftime('%Y-%m-%d')}, Last: {revenue_dates[-1].strftime('%Y-%m-%d')}")

# --- Quarterly Earnings Call Dates ---
# TSMC holds quarterly earnings calls around the 15th of Jan/Apr/Jul/Oct
# (reporting Q4/Q1/Q2/Q3 respectively)
earnings_dates = []
earnings_months = [1, 4, 7, 10]
for year in range(2015, 2027):
    for month in earnings_months:
        try:
            # Earnings calls are typically around 13th-17th; use 15th as anchor
            target = pd.Timestamp(f"{year}-{month:02d}-15")
            td = next_trading_day(target, trading_days_list)
            if td is not None and td <= etf.index[-1]:
                earnings_dates.append(td)
        except:
            pass

print(f"  Quarterly earnings call dates: {len(earnings_dates)}")
print(f"  First: {earnings_dates[0].strftime('%Y-%m-%d')}, Last: {earnings_dates[-1].strftime('%Y-%m-%d')}")

# =============================================================================
# 3. EVENT STUDY ANALYSIS FUNCTION
# =============================================================================
print("\n[3] Running event study analysis...")

def event_study(event_dates, data_etf, data_tsmc, window=5, label="Event"):
    """
    For each event date T:
    - Pre-event vol: mean(|r_{T-window}| to |r_{T-1}|)
    - Event-day vol: |r_T|
    - Post-event vol: mean(|r_{T+1}| to |r_{T+window}|)
    - TSMC individual reaction: |r_T| for 2330.TW
    Returns DataFrame with event-level results.
    """
    results = []

    for event_date in event_dates:
        # Find position in each dataset
        if event_date not in data_etf.index or event_date not in data_tsmc.index:
            continue

        etf_idx = data_etf.index.get_loc(event_date)
        tsmc_idx = data_tsmc.index.get_loc(event_date)

        # Need enough data before and after
        if etf_idx < window or etf_idx >= len(data_etf) - window:
            continue
        if tsmc_idx < window or tsmc_idx >= len(data_tsmc) - window:
            continue

        # Pre-event window
        pre_etf = data_etf['AbsReturn'].iloc[etf_idx - window:etf_idx].values
        pre_tsmc = data_tsmc['AbsReturn'].iloc[tsmc_idx - window:tsmc_idx].values

        # Event day
        event_etf = data_etf['AbsReturn'].iloc[etf_idx]
        event_tsmc = data_tsmc['AbsReturn'].iloc[tsmc_idx]
        event_ret_etf = data_etf['Return'].iloc[etf_idx]
        event_ret_tsmc = data_tsmc['Return'].iloc[tsmc_idx]

        # Post-event window
        post_etf = data_etf['AbsReturn'].iloc[etf_idx + 1:etf_idx + 1 + window].values
        post_tsmc = data_tsmc['AbsReturn'].iloc[tsmc_idx + 1:tsmc_idx + 1 + window].values

        results.append({
            'date': event_date,
            'year': event_date.year,
            'month': event_date.month,
            # ETF
            'pre_vol_etf': np.mean(pre_etf),
            'event_vol_etf': event_etf,
            'post_vol_etf': np.mean(post_etf),
            'event_ret_etf': event_ret_etf,
            # TSMC
            'pre_vol_tsmc': np.mean(pre_tsmc),
            'event_vol_tsmc': event_tsmc,
            'post_vol_tsmc': np.mean(post_tsmc),
            'event_ret_tsmc': event_ret_tsmc,
        })

    df = pd.DataFrame(results)
    return df

# Run event studies
rev_results = event_study(revenue_dates, etf, tsmc, window=5, label="Revenue")
earn_results = event_study(earnings_dates, etf, tsmc, window=5, label="Earnings")

print(f"  Revenue events with full windows: {len(rev_results)}")
print(f"  Earnings events with full windows: {len(earn_results)}")

# =============================================================================
# 4. STATISTICAL TESTS
# =============================================================================
print("\n[4] Statistical tests...")

# Normal day baseline
all_event_dates_set = set(revenue_dates + earnings_dates)
normal_days_etf = etf[~etf.index.isin(all_event_dates_set)]
normal_vol_etf = normal_days_etf['AbsReturn'].dropna()
normal_days_tsmc = tsmc[~tsmc.index.isin(all_event_dates_set)]
normal_vol_tsmc = normal_days_tsmc['AbsReturn'].dropna()

print(f"  Normal trading days (0050): {len(normal_vol_etf)}")
print(f"  Normal mean |ret| (0050): {normal_vol_etf.mean()*100:.4f}%")
print(f"  Normal mean |ret| (2330): {normal_vol_tsmc.mean()*100:.4f}%")

results_dict = {
    'experiment_id': 'k617',
    'title': 'K617: TSMC Revenue/Earnings Event Study',
    'data_source': 'yfinance (0050.TW, 2330.TW)',
    'period': f"{etf.index[0].strftime('%Y-%m-%d')} to {etf.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days_0050': len(etf),
    'n_trading_days_2330': len(tsmc),
    'baseline': {
        'normal_mean_absret_0050': round(float(normal_vol_etf.mean() * 100), 4),
        'normal_mean_absret_2330': round(float(normal_vol_tsmc.mean() * 100), 4),
    }
}

def run_tests(event_df, event_type, normal_vol_etf_vals, normal_vol_tsmc_vals):
    """Run all statistical tests for a given event type."""
    test_results = {}

    # --- Test 4a: Event-day vol vs normal day ---
    print(f"\n  --- {event_type} ---")
    print(f"  N events: {len(event_df)}")

    event_vol_etf = event_df['event_vol_etf'].values
    event_vol_tsmc = event_df['event_vol_tsmc'].values

    # 0050.TW
    mean_event = np.mean(event_vol_etf)
    mean_normal = np.mean(normal_vol_etf_vals)
    ratio_etf = mean_event / mean_normal

    t_stat_etf, p_val_etf = stats.ttest_ind(event_vol_etf, normal_vol_etf_vals, equal_var=False)
    wilcox_stat_etf, wilcox_p_etf = stats.mannwhitneyu(event_vol_etf, normal_vol_etf_vals, alternative='two-sided')

    print(f"  0050.TW event |ret|: {mean_event*100:.4f}% vs normal {mean_normal*100:.4f}%")
    print(f"  0050.TW ratio: {ratio_etf:.3f}x")
    print(f"  0050.TW t-test: t={t_stat_etf:.3f}, p={p_val_etf:.4f}")
    print(f"  0050.TW Wilcoxon: U={wilcox_stat_etf:.0f}, p={wilcox_p_etf:.4f}")

    # 2330.TW
    mean_event_tsmc = np.mean(event_vol_tsmc)
    mean_normal_tsmc = np.mean(normal_vol_tsmc_vals)
    ratio_tsmc = mean_event_tsmc / mean_normal_tsmc

    t_stat_tsmc, p_val_tsmc = stats.ttest_ind(event_vol_tsmc, normal_vol_tsmc_vals, equal_var=False)
    wilcox_stat_tsmc, wilcox_p_tsmc = stats.mannwhitneyu(event_vol_tsmc, normal_vol_tsmc_vals, alternative='two-sided')

    print(f"  2330.TW event |ret|: {mean_event_tsmc*100:.4f}% vs normal {mean_normal_tsmc*100:.4f}%")
    print(f"  2330.TW ratio: {ratio_tsmc:.3f}x")
    print(f"  2330.TW t-test: t={t_stat_tsmc:.3f}, p={p_val_tsmc:.4f}")
    print(f"  2330.TW Wilcoxon: U={wilcox_stat_tsmc:.0f}, p={wilcox_p_tsmc:.4f}")

    test_results['event_vs_normal'] = {
        '0050_TW': {
            'event_mean_absret_pct': round(float(mean_event * 100), 4),
            'normal_mean_absret_pct': round(float(mean_normal * 100), 4),
            'ratio': round(float(ratio_etf), 3),
            't_stat': round(float(t_stat_etf), 3),
            'p_value': round(float(p_val_etf), 4),
            'wilcoxon_p': round(float(wilcox_p_etf), 4),
            'significant_005': bool(p_val_etf < 0.05),
        },
        '2330_TW': {
            'event_mean_absret_pct': round(float(mean_event_tsmc * 100), 4),
            'normal_mean_absret_pct': round(float(mean_normal_tsmc * 100), 4),
            'ratio': round(float(ratio_tsmc), 3),
            't_stat': round(float(t_stat_tsmc), 3),
            'p_value': round(float(p_val_tsmc), 4),
            'wilcoxon_p': round(float(wilcox_p_tsmc), 4),
            'significant_005': bool(p_val_tsmc < 0.05),
        }
    }

    # --- Test 4b: TSMC reaction vs 0050 reaction (amplification) ---
    # Filter out zero denominators to avoid inf
    valid_amp = event_df[event_df['event_vol_etf'] > 0].copy()
    amp_factors = valid_amp['event_vol_tsmc'] / valid_amp['event_vol_etf']
    amp_factors = amp_factors.replace([np.inf, -np.inf], np.nan).dropna()
    amp_mean = amp_factors.mean()
    amp_median = amp_factors.median()

    # Test if TSMC vol > 0050 vol on event days (paired test)
    t_amp, p_amp = stats.ttest_rel(event_vol_tsmc, event_vol_etf)

    print(f"\n  TSMC vs 0050 amplification factor:")
    print(f"    Mean: {amp_mean:.3f}x, Median: {amp_median:.3f}x")
    print(f"    Paired t-test: t={t_amp:.3f}, p={p_amp:.4f}")

    test_results['amplification'] = {
        'mean_factor': round(float(amp_mean), 3),
        'median_factor': round(float(amp_median), 3),
        'paired_t_stat': round(float(t_amp), 3),
        'paired_p_value': round(float(p_amp), 4),
    }

    # --- Test 4c: Pre vs Post event vol (vol crush?) ---
    pre_vols = event_df['pre_vol_etf'].values
    post_vols = event_df['post_vol_etf'].values
    event_vols = event_df['event_vol_etf'].values

    # Event day vs pre
    t_evt_pre, p_evt_pre = stats.ttest_rel(event_vols, pre_vols)
    # Post vs pre
    t_post_pre, p_post_pre = stats.ttest_rel(post_vols, pre_vols)
    # Event vs post
    t_evt_post, p_evt_post = stats.ttest_rel(event_vols, post_vols)

    pre_mean = np.mean(pre_vols)
    post_mean = np.mean(post_vols)
    event_mean = np.mean(event_vols)

    vol_crush = (post_mean - pre_mean) / pre_mean * 100
    event_spike = (event_mean - pre_mean) / pre_mean * 100

    print(f"\n  Vol pattern (0050.TW):")
    print(f"    Pre-event avg: {pre_mean*100:.4f}%")
    print(f"    Event-day avg: {event_mean*100:.4f}% (spike: {event_spike:+.1f}%)")
    print(f"    Post-event avg: {post_mean*100:.4f}% (vs pre: {vol_crush:+.1f}%)")
    print(f"    Event vs Pre: t={t_evt_pre:.3f}, p={p_evt_pre:.4f}")
    print(f"    Post vs Pre:  t={t_post_pre:.3f}, p={p_post_pre:.4f}")
    print(f"    Event vs Post: t={t_evt_post:.3f}, p={p_evt_post:.4f}")

    test_results['vol_pattern'] = {
        'pre_event_mean_pct': round(float(pre_mean * 100), 4),
        'event_day_mean_pct': round(float(event_mean * 100), 4),
        'post_event_mean_pct': round(float(post_mean * 100), 4),
        'event_spike_pct': round(float(event_spike), 1),
        'vol_crush_pct': round(float(vol_crush), 1),
        'event_vs_pre_t': round(float(t_evt_pre), 3),
        'event_vs_pre_p': round(float(p_evt_pre), 4),
        'post_vs_pre_t': round(float(t_post_pre), 3),
        'post_vs_pre_p': round(float(p_post_pre), 4),
        'event_vs_post_t': round(float(t_evt_post), 3),
        'event_vs_post_p': round(float(p_evt_post), 4),
    }

    # --- Test 4d: Beat vs Miss (proxy: positive return = beat) ---
    positive_ret = event_df[event_df['event_ret_tsmc'] > 0]
    negative_ret = event_df[event_df['event_ret_tsmc'] <= 0]

    n_pos = len(positive_ret)
    n_neg = len(negative_ret)

    if n_pos > 5 and n_neg > 5:
        vol_beat = positive_ret['event_vol_etf'].values
        vol_miss = negative_ret['event_vol_etf'].values

        t_bm, p_bm = stats.ttest_ind(vol_beat, vol_miss, equal_var=False)

        vol_beat_tsmc = positive_ret['event_vol_tsmc'].values
        vol_miss_tsmc = negative_ret['event_vol_tsmc'].values
        t_bm_tsmc, p_bm_tsmc = stats.ttest_ind(vol_beat_tsmc, vol_miss_tsmc, equal_var=False)

        print(f"\n  Beat (TSMC ret > 0) vs Miss (ret <= 0):")
        print(f"    Beats: {n_pos} ({n_pos/(n_pos+n_neg)*100:.1f}%), Misses: {n_neg} ({n_neg/(n_pos+n_neg)*100:.1f}%)")
        print(f"    0050 |ret| on beat days: {np.mean(vol_beat)*100:.4f}%")
        print(f"    0050 |ret| on miss days: {np.mean(vol_miss)*100:.4f}%")
        print(f"    0050 t-test: t={t_bm:.3f}, p={p_bm:.4f}")
        print(f"    2330 |ret| on beat days: {np.mean(vol_beat_tsmc)*100:.4f}%")
        print(f"    2330 |ret| on miss days: {np.mean(vol_miss_tsmc)*100:.4f}%")
        print(f"    2330 t-test: t={t_bm_tsmc:.3f}, p={p_bm_tsmc:.4f}")

        test_results['beat_vs_miss'] = {
            'n_beat': int(n_pos),
            'n_miss': int(n_neg),
            'beat_pct': round(float(n_pos / (n_pos + n_neg) * 100), 1),
            '0050_beat_absret_pct': round(float(np.mean(vol_beat) * 100), 4),
            '0050_miss_absret_pct': round(float(np.mean(vol_miss) * 100), 4),
            '0050_t_stat': round(float(t_bm), 3),
            '0050_p_value': round(float(p_bm), 4),
            '2330_beat_absret_pct': round(float(np.mean(vol_beat_tsmc) * 100), 4),
            '2330_miss_absret_pct': round(float(np.mean(vol_miss_tsmc) * 100), 4),
            '2330_t_stat': round(float(t_bm_tsmc), 3),
            '2330_p_value': round(float(p_bm_tsmc), 4),
        }
    else:
        print(f"\n  Beat vs Miss: insufficient data (pos={n_pos}, neg={n_neg})")
        test_results['beat_vs_miss'] = {'insufficient_data': True}

    return test_results

# Run tests for both event types
rev_tests = run_tests(rev_results, "Monthly Revenue", normal_vol_etf.values, normal_vol_tsmc.values)
earn_tests = run_tests(earn_results, "Quarterly Earnings", normal_vol_etf.values, normal_vol_tsmc.values)

results_dict['monthly_revenue'] = {
    'n_events': len(rev_results),
    'tests': rev_tests,
}
results_dict['quarterly_earnings'] = {
    'n_events': len(earn_results),
    'tests': earn_tests,
}

# =============================================================================
# 5. REVENUE vs EARNINGS COMPARISON
# =============================================================================
print("\n\n[5] Revenue vs Earnings comparison...")

rev_event_vol = rev_results['event_vol_etf'].values
earn_event_vol = earn_results['event_vol_etf'].values

t_re, p_re = stats.ttest_ind(earn_event_vol, rev_event_vol, equal_var=False)
wilcox_re, wilcox_p_re = stats.mannwhitneyu(earn_event_vol, rev_event_vol, alternative='two-sided')

print(f"  Revenue event |ret| (0050): {np.mean(rev_event_vol)*100:.4f}%")
print(f"  Earnings event |ret| (0050): {np.mean(earn_event_vol)*100:.4f}%")
print(f"  Earnings/Revenue ratio: {np.mean(earn_event_vol)/np.mean(rev_event_vol):.3f}x")
print(f"  t-test (earnings > revenue): t={t_re:.3f}, p={p_re:.4f}")
print(f"  Wilcoxon: U={wilcox_re:.0f}, p={wilcox_p_re:.4f}")

rev_event_vol_tsmc = rev_results['event_vol_tsmc'].values
earn_event_vol_tsmc = earn_results['event_vol_tsmc'].values

t_re_tsmc, p_re_tsmc = stats.ttest_ind(earn_event_vol_tsmc, rev_event_vol_tsmc, equal_var=False)

print(f"\n  Revenue event |ret| (2330): {np.mean(rev_event_vol_tsmc)*100:.4f}%")
print(f"  Earnings event |ret| (2330): {np.mean(earn_event_vol_tsmc)*100:.4f}%")
print(f"  Earnings/Revenue ratio: {np.mean(earn_event_vol_tsmc)/np.mean(rev_event_vol_tsmc):.3f}x")
print(f"  t-test: t={t_re_tsmc:.3f}, p={p_re_tsmc:.4f}")

results_dict['revenue_vs_earnings'] = {
    '0050_TW': {
        'revenue_mean_absret_pct': round(float(np.mean(rev_event_vol) * 100), 4),
        'earnings_mean_absret_pct': round(float(np.mean(earn_event_vol) * 100), 4),
        'earnings_revenue_ratio': round(float(np.mean(earn_event_vol) / np.mean(rev_event_vol)), 3),
        't_stat': round(float(t_re), 3),
        'p_value': round(float(p_re), 4),
        'wilcoxon_p': round(float(wilcox_p_re), 4),
    },
    '2330_TW': {
        'revenue_mean_absret_pct': round(float(np.mean(rev_event_vol_tsmc) * 100), 4),
        'earnings_mean_absret_pct': round(float(np.mean(earn_event_vol_tsmc) * 100), 4),
        'earnings_revenue_ratio': round(float(np.mean(earn_event_vol_tsmc) / np.mean(rev_event_vol_tsmc)), 3),
        't_stat': round(float(t_re_tsmc), 3),
        'p_value': round(float(p_re_tsmc), 4),
    }
}

# =============================================================================
# 6. EVENT-WINDOW PROFILE [-5, +5]
# =============================================================================
print("\n[6] Event-window vol profile [-5, +5]...")

def compute_event_profile(event_dates_list, data, window=5):
    """Compute average |return| for each day in [-window, +window] around events."""
    profiles = []
    for event_date in event_dates_list:
        if event_date not in data.index:
            continue
        idx = data.index.get_loc(event_date)
        if idx < window or idx >= len(data) - window:
            continue

        profile = {}
        for offset in range(-window, window + 1):
            profile[offset] = data['AbsReturn'].iloc[idx + offset]
        profiles.append(profile)

    if not profiles:
        return {}

    df = pd.DataFrame(profiles)
    result = {}
    for col in df.columns:
        result[col] = {
            'mean': float(df[col].mean()),
            'median': float(df[col].median()),
            'std': float(df[col].std()),
        }
    return result

rev_profile_etf = compute_event_profile(revenue_dates, etf)
rev_profile_tsmc = compute_event_profile(revenue_dates, tsmc)
earn_profile_etf = compute_event_profile(earnings_dates, etf)
earn_profile_tsmc = compute_event_profile(earnings_dates, tsmc)

print("\n  Revenue Announcement Vol Profile (0050.TW, mean |ret| %):")
print("  Day  |  0050.TW  |  2330.TW")
print("  " + "-" * 35)
for offset in range(-5, 6):
    etf_val = rev_profile_etf.get(offset, {}).get('mean', 0) * 100
    tsmc_val = rev_profile_tsmc.get(offset, {}).get('mean', 0) * 100
    marker = " <--" if offset == 0 else ""
    print(f"  {offset:+2d}   |  {etf_val:.4f}%  |  {tsmc_val:.4f}%{marker}")

print("\n  Earnings Call Vol Profile (0050.TW, mean |ret| %):")
print("  Day  |  0050.TW  |  2330.TW")
print("  " + "-" * 35)
for offset in range(-5, 6):
    etf_val = earn_profile_etf.get(offset, {}).get('mean', 0) * 100
    tsmc_val = earn_profile_tsmc.get(offset, {}).get('mean', 0) * 100
    marker = " <--" if offset == 0 else ""
    print(f"  {offset:+2d}   |  {etf_val:.4f}%  |  {tsmc_val:.4f}%{marker}")

# Store profiles (convert int keys to strings for JSON)
results_dict['event_profiles'] = {
    'revenue_0050': {str(k): v for k, v in rev_profile_etf.items()},
    'revenue_2330': {str(k): v for k, v in rev_profile_tsmc.items()},
    'earnings_0050': {str(k): v for k, v in earn_profile_etf.items()},
    'earnings_2330': {str(k): v for k, v in earn_profile_tsmc.items()},
}

# =============================================================================
# 7. TEMPORAL STABILITY (rolling 3-year windows)
# =============================================================================
print("\n[7] Temporal stability analysis (rolling 3-year windows)...")

def temporal_stability(event_df, normal_vol, label):
    """Check if the event effect is stable across sub-periods."""
    years = sorted(event_df['year'].unique())
    window_size = 3
    results = []

    for start_year in range(years[0], years[-1] - window_size + 2):
        end_year = start_year + window_size - 1
        sub = event_df[(event_df['year'] >= start_year) & (event_df['year'] <= end_year)]
        if len(sub) < 10:
            continue

        event_vol = sub['event_vol_etf'].values
        ratio = np.mean(event_vol) / np.mean(normal_vol)
        t_stat, p_val = stats.ttest_ind(event_vol, normal_vol, equal_var=False)

        results.append({
            'period': f"{start_year}-{end_year}",
            'n_events': len(sub),
            'ratio': round(float(ratio), 3),
            't_stat': round(float(t_stat), 3),
            'p_value': round(float(p_val), 4),
        })
        print(f"  {label} {start_year}-{end_year}: N={len(sub)}, ratio={ratio:.3f}x, t={t_stat:.3f}, p={p_val:.4f}")

    return results

print("\n  Monthly Revenue temporal stability (0050.TW):")
rev_stability = temporal_stability(rev_results, normal_vol_etf.values, "Revenue")

print("\n  Quarterly Earnings temporal stability (0050.TW):")
earn_stability = temporal_stability(earn_results, normal_vol_etf.values, "Earnings")

results_dict['temporal_stability'] = {
    'revenue': rev_stability,
    'earnings': earn_stability,
}

# =============================================================================
# 8. COMBINED EVENT DAY ANALYSIS (Revenue + Earnings overlap check)
# =============================================================================
print("\n[8] Overlap analysis...")

rev_set = set(pd.Timestamp(d).normalize() for d in revenue_dates)
earn_set = set(pd.Timestamp(d).normalize() for d in earnings_dates)
overlap = rev_set & earn_set

print(f"  Revenue dates: {len(rev_set)}")
print(f"  Earnings dates: {len(earn_set)}")
print(f"  Overlap dates: {len(overlap)}")
if overlap:
    overlap_sorted = sorted(overlap)
    print(f"  Overlap examples: {[d.strftime('%Y-%m-%d') for d in overlap_sorted[:5]]}")

results_dict['overlap'] = {
    'n_revenue': len(rev_set),
    'n_earnings': len(earn_set),
    'n_overlap': len(overlap),
    'overlap_dates': [d.strftime('%Y-%m-%d') for d in sorted(overlap)],
}

# =============================================================================
# 9. PRACTICAL IMPLICATIONS FOR APRIL 2026
# =============================================================================
print("\n[9] Practical implications for April 2026...")

# April 10 = revenue announcement, April 15-16 = earnings call
print("  Upcoming TSMC events:")
print("  - 04/10 (Fri): March monthly revenue announcement")
print("  - 04/16 (Thu): Q1 2026 earnings call")

# Average the effects
rev_ratio_0050 = results_dict['monthly_revenue']['tests']['event_vs_normal']['0050_TW']['ratio']
earn_ratio_0050 = results_dict['quarterly_earnings']['tests']['event_vs_normal']['0050_TW']['ratio']
rev_ratio_2330 = results_dict['monthly_revenue']['tests']['event_vs_normal']['2330_TW']['ratio']
earn_ratio_2330 = results_dict['quarterly_earnings']['tests']['event_vs_normal']['2330_TW']['ratio']

print(f"\n  Expected vol multiplier on 04/10 (revenue):")
print(f"    0050.TW: {rev_ratio_0050:.3f}x normal")
print(f"    2330.TW: {rev_ratio_2330:.3f}x normal")
print(f"\n  Expected vol multiplier on 04/16 (earnings):")
print(f"    0050.TW: {earn_ratio_0050:.3f}x normal")
print(f"    2330.TW: {earn_ratio_2330:.3f}x normal")

results_dict['april_2026_forecast'] = {
    'revenue_0410': {
        '0050_vol_multiplier': rev_ratio_0050,
        '2330_vol_multiplier': rev_ratio_2330,
    },
    'earnings_0416': {
        '0050_vol_multiplier': earn_ratio_0050,
        '2330_vol_multiplier': earn_ratio_2330,
    },
}

# =============================================================================
# 10. SUMMARY
# =============================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

rev_sig_0050 = results_dict['monthly_revenue']['tests']['event_vs_normal']['0050_TW']['significant_005']
rev_sig_2330 = results_dict['monthly_revenue']['tests']['event_vs_normal']['2330_TW']['significant_005']
earn_sig_0050 = results_dict['quarterly_earnings']['tests']['event_vs_normal']['0050_TW']['significant_005']
earn_sig_2330 = results_dict['quarterly_earnings']['tests']['event_vs_normal']['2330_TW']['significant_005']

print(f"\n  Monthly Revenue (N={len(rev_results)}):")
print(f"    0050.TW: {rev_ratio_0050:.3f}x, sig={rev_sig_0050}")
print(f"    2330.TW: {rev_ratio_2330:.3f}x, sig={rev_sig_2330}")

print(f"\n  Quarterly Earnings (N={len(earn_results)}):")
print(f"    0050.TW: {earn_ratio_0050:.3f}x, sig={earn_sig_0050}")
print(f"    2330.TW: {earn_ratio_2330:.3f}x, sig={earn_sig_2330}")

rev_spike = results_dict['monthly_revenue']['tests']['vol_pattern']['event_spike_pct']
earn_spike = results_dict['quarterly_earnings']['tests']['vol_pattern']['event_spike_pct']
rev_crush = results_dict['monthly_revenue']['tests']['vol_pattern']['vol_crush_pct']
earn_crush = results_dict['quarterly_earnings']['tests']['vol_pattern']['vol_crush_pct']

print(f"\n  Event-day spike (vs pre-5d avg):")
print(f"    Revenue: {rev_spike:+.1f}%")
print(f"    Earnings: {earn_spike:+.1f}%")

print(f"\n  Post-event vol change (vs pre-5d avg):")
print(f"    Revenue: {rev_crush:+.1f}%")
print(f"    Earnings: {earn_crush:+.1f}%")

amp_rev = results_dict['monthly_revenue']['tests']['amplification']
amp_earn = results_dict['quarterly_earnings']['tests']['amplification']
print(f"\n  TSMC vs 0050 amplification:")
print(f"    Revenue: {amp_rev['mean_factor']:.3f}x (median {amp_rev['median_factor']:.3f}x)")
print(f"    Earnings: {amp_earn['mean_factor']:.3f}x (median {amp_earn['median_factor']:.3f}x)")

# Determine overall star rating
any_significant = rev_sig_0050 or rev_sig_2330 or earn_sig_0050 or earn_sig_2330
star = "★" if any_significant else "☆"

summary_lines = []
if rev_sig_0050 or rev_sig_2330:
    summary_lines.append(f"Revenue: 0050 {rev_ratio_0050:.2f}x{'*' if rev_sig_0050 else ''}, 2330 {rev_ratio_2330:.2f}x{'*' if rev_sig_2330 else ''}")
if earn_sig_0050 or earn_sig_2330:
    summary_lines.append(f"Earnings: 0050 {earn_ratio_0050:.2f}x{'*' if earn_sig_0050 else ''}, 2330 {earn_ratio_2330:.2f}x{'*' if earn_sig_2330 else ''}")

amp_str = f"TSMC/0050 amp: rev {amp_rev['mean_factor']:.1f}x, earn {amp_earn['mean_factor']:.1f}x"
summary_lines.append(amp_str)

title_str = f"K617: {star} TSMC Event Study — {'; '.join(summary_lines)}"

results_dict['summary'] = {
    'title': title_str,
    'star': star,
    'any_significant': any_significant,
    'revenue_sig_0050': rev_sig_0050,
    'revenue_sig_2330': rev_sig_2330,
    'earnings_sig_0050': earn_sig_0050,
    'earnings_sig_2330': earn_sig_2330,
}

print(f"\n  Title: {title_str}")
print("\n" + "=" * 70)

# =============================================================================
# SAVE RESULTS
# =============================================================================
output_path = 'experiments/k617_tsmc_event_study_results.json'
with open(output_path, 'w') as f:
    json.dump(results_dict, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")
print("Done.")
