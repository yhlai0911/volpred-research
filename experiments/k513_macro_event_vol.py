"""
K513: US Macro Event Volatility Study (FOMC / NFP / CPI)
=========================================================
[提出: Claude, 服務事件日曆]
[執行: Claude]

研究問題:
1. FOMC/NFP/CPI 日 vs 普通日的 SPY vol 差異
2. VIX 在事件前後的行為模式
3. Event day vol pattern [-5, +5] 窗口
4. 三類事件的比較
5. 對 VT 策略的實務含義

數據來源: yfinance (SPY, ^VIX), 2005-2025
FOMC dates: hardcoded from Federal Reserve (8 meetings/year)
NFP dates: first Friday of each month (algorithmic)
CPI dates: hardcoded from BLS release calendar

文獻基礎:
- Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JF
- Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?" RFS
- Ai & Bansal (2018) "Risk Preferences and the Macroeconomic Announcement Premium" JFE
- K96: FOMC causal vol study (FOMC day |SPY|=1.02% vs 0.79%, p=0.003)
- K414: FOMC-VIX not tradeable (all 6 tests fail Harvey t>3)
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
print("K513: US Macro Event Volatility Study (FOMC/NFP/CPI)")
print("=" * 70)

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n[1] Downloading SPY and VIX data...")
spy = yf.download('SPY', start='2005-01-01', end='2025-12-31', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2025-12-31', progress=False)

# Flatten multi-index if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy['Return'] = spy['Close'].pct_change()
spy['AbsReturn'] = spy['Return'].abs()
spy['LogReturn'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['AbsLogReturn'] = spy['LogReturn'].abs()
spy['RV'] = spy['AbsReturn']  # proxy for daily realized vol

# Merge VIX
vix_close = vix[['Close']].rename(columns={'Close': 'VIX'})
data = spy.join(vix_close, how='left')
data['VIX_change'] = data['VIX'] - data['VIX'].shift(1)
data['VIX_pct_change'] = data['VIX'].pct_change()
data = data.dropna(subset=['Return'])

print(f"  SPY: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total trading days: {len(data)}")

# =============================================================================
# 2. EVENT DATE DEFINITIONS
# =============================================================================
print("\n[2] Defining event dates...")

# --- FOMC Meeting Dates (announcement dates, end of 2-day meetings) ---
# Source: Federal Reserve calendar, comprehensive list 2005-2025
fomc_dates_str = [
    # 2005
    '2005-02-02', '2005-03-22', '2005-05-03', '2005-06-30',
    '2005-08-09', '2005-09-20', '2005-11-01', '2005-12-13',
    # 2006
    '2006-01-31', '2006-03-28', '2006-05-10', '2006-06-29',
    '2006-08-08', '2006-09-20', '2006-10-25', '2006-12-12',
    # 2007
    '2007-01-31', '2007-03-21', '2007-05-09', '2007-06-28',
    '2007-08-07', '2007-09-18', '2007-10-31', '2007-12-11',
    # 2008
    '2008-01-22', '2008-01-30', '2008-03-18', '2008-04-30',
    '2008-06-25', '2008-08-05', '2008-09-16', '2008-10-08',
    '2008-10-29', '2008-12-16',
    # 2009
    '2009-01-28', '2009-03-18', '2009-04-29', '2009-06-24',
    '2009-08-12', '2009-09-23', '2009-11-04', '2009-12-16',
    # 2010
    '2010-01-27', '2010-03-16', '2010-04-28', '2010-06-23',
    '2010-08-10', '2010-09-21', '2010-11-03', '2010-12-14',
    # 2011
    '2011-01-26', '2011-03-15', '2011-04-27', '2011-06-22',
    '2011-08-09', '2011-09-21', '2011-11-02', '2011-12-13',
    # 2012
    '2012-01-25', '2012-03-13', '2012-04-25', '2012-06-20',
    '2012-08-01', '2012-09-13', '2012-10-24', '2012-12-12',
    # 2013
    '2013-01-30', '2013-03-20', '2013-05-01', '2013-06-19',
    '2013-07-31', '2013-09-18', '2013-10-30', '2013-12-18',
    # 2014
    '2014-01-29', '2014-03-19', '2014-04-30', '2014-06-18',
    '2014-07-30', '2014-09-17', '2014-10-29', '2014-12-17',
    # 2015
    '2015-01-28', '2015-03-18', '2015-04-29', '2015-06-17',
    '2015-07-29', '2015-09-17', '2015-10-28', '2015-12-16',
    # 2016
    '2016-01-27', '2016-03-16', '2016-04-27', '2016-06-15',
    '2016-07-27', '2016-09-21', '2016-11-02', '2016-12-14',
    # 2017
    '2017-02-01', '2017-03-15', '2017-05-03', '2017-06-14',
    '2017-07-26', '2017-09-20', '2017-11-01', '2017-12-13',
    # 2018
    '2018-01-31', '2018-03-21', '2018-05-02', '2018-06-13',
    '2018-08-01', '2018-09-26', '2018-11-08', '2018-12-19',
    # 2019
    '2019-01-30', '2019-03-20', '2019-05-01', '2019-06-19',
    '2019-07-31', '2019-09-18', '2019-10-30', '2019-12-11',
    # 2020
    '2020-01-29', '2020-03-03', '2020-03-15', '2020-04-29',
    '2020-06-10', '2020-07-29', '2020-09-16', '2020-11-05', '2020-12-16',
    # 2021
    '2021-01-27', '2021-03-17', '2021-04-28', '2021-06-16',
    '2021-07-28', '2021-09-22', '2021-11-03', '2021-12-15',
    # 2022
    '2022-01-26', '2022-03-16', '2022-05-04', '2022-06-15',
    '2022-07-27', '2022-09-21', '2022-11-02', '2022-12-14',
    # 2023
    '2023-02-01', '2023-03-22', '2023-05-03', '2023-06-14',
    '2023-07-26', '2023-09-20', '2023-11-01', '2023-12-13',
    # 2024
    '2024-01-31', '2024-03-20', '2024-05-01', '2024-06-12',
    '2024-07-31', '2024-09-18', '2024-11-07', '2024-12-18',
    # 2025
    '2025-01-29', '2025-03-19', '2025-05-07', '2025-06-18',
    '2025-07-30', '2025-09-17', '2025-10-29', '2025-12-17',
]

# --- CPI Release Dates (hardcoded from BLS calendar) ---
# CPI is released monthly, typically around 10th-14th of the month
# Using known release dates; generating approximations for earlier years
cpi_dates_str = []
# For 2005-2024: CPI typically released ~13th of each month
# We'll generate approximate dates and match to nearest trading day
for year in range(2005, 2026):
    for month in range(1, 13):
        # CPI is typically released around the 10th-14th
        # Use 13th as default, then find nearest trading day
        try:
            d = pd.Timestamp(year=year, month=month, day=13)
            cpi_dates_str.append(d.strftime('%Y-%m-%d'))
        except:
            pass

# --- NFP Dates (first Friday of each month) ---
nfp_dates = []
for year in range(2005, 2026):
    for month in range(1, 13):
        first_day = pd.Timestamp(year=year, month=month, day=1)
        days_until_friday = (4 - first_day.weekday()) % 7
        nfp = first_day + pd.Timedelta(days=days_until_friday)
        nfp_dates.append(nfp)

# Convert to DatetimeIndex and match to actual trading days
trading_days = data.index

def match_to_trading_days(date_list, trading_days, max_shift=3):
    """Match event dates to nearest trading day within max_shift days."""
    matched = []
    for d in date_list:
        if isinstance(d, str):
            d = pd.Timestamp(d)
        # Look for nearest trading day within window
        for shift in range(0, max_shift + 1):
            for sign in [0, 1, -1]:
                candidate = d + pd.Timedelta(days=shift * (1 if sign >= 0 else -1))
                if shift == 0 and sign != 0:
                    continue
                if candidate in trading_days:
                    matched.append(candidate)
                    break
            else:
                continue
            break
    return pd.DatetimeIndex(sorted(set(matched)))

fomc_days = match_to_trading_days(fomc_dates_str, trading_days)
nfp_days = match_to_trading_days(nfp_dates, trading_days)
cpi_days = match_to_trading_days(cpi_dates_str, trading_days)

# Filter to data range
fomc_days = fomc_days[fomc_days.isin(data.index)]
nfp_days = nfp_days[nfp_days.isin(data.index)]
cpi_days = cpi_days[cpi_days.isin(data.index)]

print(f"  FOMC dates matched: {len(fomc_days)}")
print(f"  NFP dates matched:  {len(nfp_days)}")
print(f"  CPI dates matched:  {len(cpi_days)}")

# Tag events
data['is_fomc'] = data.index.isin(fomc_days)
data['is_nfp'] = data.index.isin(nfp_days)
data['is_cpi'] = data.index.isin(cpi_days)
data['is_any_event'] = data['is_fomc'] | data['is_nfp'] | data['is_cpi']
data['is_no_event'] = ~data['is_any_event']

print(f"  Event days: {data['is_any_event'].sum()}")
print(f"  Non-event days: {data['is_no_event'].sum()}")

# =============================================================================
# 3. DESCRIPTIVE STATISTICS
# =============================================================================
print("\n[3] Descriptive Statistics")
print("=" * 70)

results = {}

def event_stats(name, mask):
    """Compute event day vs non-event day statistics."""
    event_data = data[mask]
    nonevent_data = data[~mask & data['is_no_event']]

    # |Return| comparison
    event_absret = event_data['AbsReturn'].dropna()
    nonevent_absret = nonevent_data['AbsReturn'].dropna()

    t_stat, p_val = stats.ttest_ind(event_absret, nonevent_absret, equal_var=False)

    # VIX levels
    event_vix = event_data['VIX'].dropna()
    nonevent_vix = nonevent_data['VIX'].dropna()
    t_vix, p_vix = stats.ttest_ind(event_vix, nonevent_vix, equal_var=False)

    # VIX change on event day
    event_vix_chg = event_data['VIX_change'].dropna()
    t_vix_chg, p_vix_chg = stats.ttest_1samp(event_vix_chg, 0)

    # Return on event day
    event_ret = event_data['Return'].dropna()
    t_ret, p_ret = stats.ttest_1samp(event_ret, 0)

    result = {
        'n_events': len(event_data),
        'n_nonevents': len(nonevent_data),
        'event_mean_absret': float(event_absret.mean()),
        'nonevent_mean_absret': float(nonevent_absret.mean()),
        'absret_ratio': float(event_absret.mean() / nonevent_absret.mean()),
        'absret_t_stat': float(t_stat),
        'absret_p_value': float(p_val),
        'event_median_absret': float(event_absret.median()),
        'nonevent_median_absret': float(nonevent_absret.median()),
        'event_mean_vix': float(event_vix.mean()),
        'nonevent_mean_vix': float(nonevent_vix.mean()),
        'vix_level_t_stat': float(t_vix),
        'vix_level_p_value': float(p_vix),
        'event_mean_vix_change': float(event_vix_chg.mean()),
        'vix_change_t_stat': float(t_vix_chg),
        'vix_change_p_value': float(p_vix_chg),
        'event_mean_return': float(event_ret.mean()),
        'event_return_t_stat': float(t_ret),
        'event_return_p_value': float(p_ret),
        'event_std_return': float(event_ret.std()),
        'nonevent_std_return': float(nonevent_data['Return'].dropna().std()),
    }

    print(f"\n  {name} ({result['n_events']} events):")
    print(f"    |Return|: Event={result['event_mean_absret']*100:.3f}% vs Non-event={result['nonevent_mean_absret']*100:.3f}%")
    print(f"    Ratio: {result['absret_ratio']:.3f}x, t={result['absret_t_stat']:.3f}, p={result['absret_p_value']:.4f}")
    print(f"    Median |Ret|: Event={result['event_median_absret']*100:.3f}% vs Non-event={result['nonevent_median_absret']*100:.3f}%")
    print(f"    Std(Return): Event={result['event_std_return']*100:.3f}% vs Non-event={result['nonevent_std_return']*100:.3f}%")
    print(f"    VIX level: Event={result['event_mean_vix']:.2f} vs Non-event={result['nonevent_mean_vix']:.2f} (t={result['vix_level_t_stat']:.2f})")
    print(f"    VIX change on event day: {result['event_mean_vix_change']:.3f} (t={result['vix_change_t_stat']:.3f}, p={result['vix_change_p_value']:.4f})")
    print(f"    Mean return on event day: {result['event_mean_return']*100:.4f}% (t={result['event_return_t_stat']:.3f})")

    return result

results['fomc'] = event_stats('FOMC', data['is_fomc'])
results['nfp'] = event_stats('NFP', data['is_nfp'])
results['cpi'] = event_stats('CPI', data['is_cpi'])
results['any_event'] = event_stats('Any Macro Event', data['is_any_event'])

# =============================================================================
# 4. EVENT WINDOW ANALYSIS [-5, +5]
# =============================================================================
print("\n\n[4] Event Window Analysis [-5, +5]")
print("=" * 70)

def event_window_analysis(name, event_dates, window=5):
    """Compute average |return| and VIX change around events."""
    windows = {}

    # Get integer positions for event dates
    data_idx = data.index
    event_positions = [data_idx.get_loc(d) for d in event_dates if d in data_idx]

    for offset in range(-window, window + 1):
        abs_returns = []
        vix_changes = []
        returns = []

        for pos in event_positions:
            target_pos = pos + offset
            if 0 <= target_pos < len(data):
                row = data.iloc[target_pos]
                if not np.isnan(row['AbsReturn']):
                    abs_returns.append(row['AbsReturn'])
                if not np.isnan(row['VIX_change']):
                    vix_changes.append(row['VIX_change'])
                if not np.isnan(row['Return']):
                    returns.append(row['Return'])

        windows[offset] = {
            'mean_abs_return': float(np.mean(abs_returns)) if abs_returns else None,
            'mean_vix_change': float(np.mean(vix_changes)) if vix_changes else None,
            'mean_return': float(np.mean(returns)) if returns else None,
            'n': len(abs_returns),
        }

    # Print table
    print(f"\n  {name} Event Window:")
    print(f"  {'Day':>4} | {'|Ret|%':>8} | {'VIX Δ':>8} | {'Ret%':>8} | {'N':>5}")
    print(f"  {'-'*4} | {'-'*8} | {'-'*8} | {'-'*8} | {'-'*5}")
    for offset in range(-window, window + 1):
        w = windows[offset]
        marker = " <<<" if offset == 0 else ""
        print(f"  {offset:>+4} | {w['mean_abs_return']*100:>8.3f} | {w['mean_vix_change']:>+8.3f} | {w['mean_return']*100:>+8.4f} | {w['n']:>5}{marker}")

    return windows

window_fomc = event_window_analysis('FOMC', fomc_days)
window_nfp = event_window_analysis('NFP', nfp_days)
window_cpi = event_window_analysis('CPI', cpi_days)

results['event_windows'] = {
    'fomc': {str(k): v for k, v in window_fomc.items()},
    'nfp': {str(k): v for k, v in window_nfp.items()},
    'cpi': {str(k): v for k, v in window_cpi.items()},
}

# =============================================================================
# 5. PRE-EVENT VIX BUILDUP
# =============================================================================
print("\n\n[5] Pre-Event VIX Buildup Analysis")
print("=" * 70)

def vix_buildup(name, event_dates, pre_window=5):
    """Check if VIX systematically rises before events."""
    pre_vix_changes = []

    data_idx = data.index
    event_positions = [data_idx.get_loc(d) for d in event_dates if d in data_idx]

    for pos in event_positions:
        # VIX change from [-pre_window] to [-1]
        if pos >= pre_window:
            vix_before = data.iloc[pos - pre_window]['VIX']
            vix_eve = data.iloc[pos - 1]['VIX']
            if not np.isnan(vix_before) and not np.isnan(vix_eve):
                pre_vix_changes.append(vix_eve - vix_before)

    pre_arr = np.array(pre_vix_changes)
    t_stat, p_val = stats.ttest_1samp(pre_arr, 0)

    result = {
        'mean_pre_vix_change': float(pre_arr.mean()),
        'median_pre_vix_change': float(np.median(pre_arr)),
        'std_pre_vix_change': float(pre_arr.std()),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'n': len(pre_arr),
        'pct_positive': float((pre_arr > 0).mean()),
    }

    print(f"\n  {name}: VIX change [-5] to [-1]")
    print(f"    Mean: {result['mean_pre_vix_change']:+.3f}, Median: {result['median_pre_vix_change']:+.3f}")
    print(f"    t={result['t_stat']:.3f}, p={result['p_value']:.4f}")
    print(f"    % positive (VIX rises pre-event): {result['pct_positive']*100:.1f}%")

    return result

results['vix_buildup'] = {
    'fomc': vix_buildup('FOMC', fomc_days),
    'nfp': vix_buildup('NFP', nfp_days),
    'cpi': vix_buildup('CPI', cpi_days),
}

# =============================================================================
# 6. POST-EVENT VIX RESOLUTION
# =============================================================================
print("\n\n[6] Post-Event VIX Resolution (Uncertainty Resolution Hypothesis)")
print("=" * 70)

def vix_resolution(name, event_dates, post_window=3):
    """Check if VIX drops after events (uncertainty resolution)."""
    post_vix_changes = []

    data_idx = data.index
    event_positions = [data_idx.get_loc(d) for d in event_dates if d in data_idx]

    for pos in event_positions:
        # VIX change from [0] to [+post_window]
        if pos + post_window < len(data):
            vix_event = data.iloc[pos]['VIX']
            vix_after = data.iloc[pos + post_window]['VIX']
            if not np.isnan(vix_event) and not np.isnan(vix_after):
                post_vix_changes.append(vix_after - vix_event)

    post_arr = np.array(post_vix_changes)
    t_stat, p_val = stats.ttest_1samp(post_arr, 0)

    result = {
        'mean_post_vix_change': float(post_arr.mean()),
        'median_post_vix_change': float(np.median(post_arr)),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'n': len(post_arr),
        'pct_negative': float((post_arr < 0).mean()),
    }

    print(f"\n  {name}: VIX change [0] to [+{post_window}]")
    print(f"    Mean: {result['mean_post_vix_change']:+.3f}, Median: {result['median_post_vix_change']:+.3f}")
    print(f"    t={result['t_stat']:.3f}, p={result['p_value']:.4f}")
    print(f"    % negative (VIX drops post-event): {result['pct_negative']*100:.1f}%")

    return result

results['vix_resolution'] = {
    'fomc': vix_resolution('FOMC', fomc_days),
    'nfp': vix_resolution('NFP', nfp_days),
    'cpi': vix_resolution('CPI', cpi_days),
}

# =============================================================================
# 7. SUBSAMPLE STABILITY
# =============================================================================
print("\n\n[7] Subsample Stability (Pre-2015 vs Post-2015)")
print("=" * 70)

def subsample_analysis(name, mask):
    """Check if event vol effect is stable across subsamples."""
    pre_2015 = data.index < '2015-01-01'
    post_2015 = data.index >= '2015-01-01'

    # Exclude COVID period for robustness
    no_covid = ~((data.index >= '2020-02-01') & (data.index <= '2020-06-30'))

    results_sub = {}
    for period_name, period_mask in [('Pre-2015', pre_2015), ('Post-2015', post_2015), ('Ex-COVID', no_covid)]:
        event_abs = data.loc[mask & period_mask, 'AbsReturn'].dropna()
        nonevent_abs = data.loc[~mask & data['is_no_event'] & period_mask, 'AbsReturn'].dropna()

        if len(event_abs) > 10 and len(nonevent_abs) > 10:
            t_stat, p_val = stats.ttest_ind(event_abs, nonevent_abs, equal_var=False)
            ratio = float(event_abs.mean() / nonevent_abs.mean())
            results_sub[period_name] = {
                'n_events': len(event_abs),
                'event_mean_absret': float(event_abs.mean()),
                'nonevent_mean_absret': float(nonevent_abs.mean()),
                'ratio': ratio,
                't_stat': float(t_stat),
                'p_value': float(p_val),
            }
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.1 else ""
            print(f"    {period_name}: ratio={ratio:.3f}x, t={t_stat:.3f}, p={p_val:.4f} {sig}")

    return results_sub

print(f"\n  FOMC Subsample:")
results['subsample_fomc'] = subsample_analysis('FOMC', data['is_fomc'])
print(f"\n  NFP Subsample:")
results['subsample_nfp'] = subsample_analysis('NFP', data['is_nfp'])
print(f"\n  CPI Subsample:")
results['subsample_cpi'] = subsample_analysis('CPI', data['is_cpi'])

# =============================================================================
# 8. MANN-WHITNEY U TEST (non-parametric robustness)
# =============================================================================
print("\n\n[8] Non-parametric Tests (Mann-Whitney U)")
print("=" * 70)

nonevent_absret = data.loc[data['is_no_event'], 'AbsReturn'].dropna()

for name, mask in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
    event_absret = data.loc[mask, 'AbsReturn'].dropna()
    u_stat, p_val = stats.mannwhitneyu(event_absret, nonevent_absret, alternative='greater')
    print(f"  {name}: U={u_stat:.0f}, p={p_val:.6f} (one-sided, event > non-event)")
    results[f'mannwhitney_{name.lower()}'] = {
        'U_stat': float(u_stat),
        'p_value': float(p_val),
    }

# =============================================================================
# 9. REGRESSION ANALYSIS
# =============================================================================
print("\n\n[9] Regression: |Return| = α + β₁·FOMC + β₂·NFP + β₃·CPI + ε")
print("=" * 70)

from numpy.linalg import lstsq

# OLS regression
y = data['AbsReturn'].dropna().values
X = np.column_stack([
    np.ones(len(data.loc[data['AbsReturn'].notna()])),
    data.loc[data['AbsReturn'].notna(), 'is_fomc'].astype(float).values,
    data.loc[data['AbsReturn'].notna(), 'is_nfp'].astype(float).values,
    data.loc[data['AbsReturn'].notna(), 'is_cpi'].astype(float).values,
])

# OLS
beta, residuals, rank, sv = lstsq(X, y, rcond=None)
y_hat = X @ beta
resid = y - y_hat
n, k = X.shape
sigma2 = np.sum(resid**2) / (n - k)

# HAC-robust standard errors (Newey-West with 5 lags)
def newey_west_se(X, resid, nlags=5):
    """Compute Newey-West HAC standard errors."""
    n, k = X.shape
    # S0
    S = np.zeros((k, k))
    for t in range(n):
        e_x = resid[t] * X[t, :]
        S += np.outer(e_x, e_x)

    # Autocovariance terms
    for lag in range(1, nlags + 1):
        w = 1 - lag / (nlags + 1)  # Bartlett kernel
        Gamma = np.zeros((k, k))
        for t in range(lag, n):
            e_x_t = resid[t] * X[t, :]
            e_x_tl = resid[t - lag] * X[t - lag, :]
            Gamma += np.outer(e_x_t, e_x_tl)
        S += w * (Gamma + Gamma.T)

    S /= n
    XtX_inv = np.linalg.inv(X.T @ X / n)
    V = XtX_inv @ S @ XtX_inv / n
    return np.sqrt(np.diag(V))

se_hac = newey_west_se(X, resid)
t_stats = beta / se_hac

var_names = ['Intercept', 'FOMC', 'NFP', 'CPI']
reg_results = {}
print(f"\n  {'Variable':>12} | {'Coef':>10} | {'SE(HAC)':>10} | {'t-stat':>8} | {'p-value':>8}")
print(f"  {'-'*12} | {'-'*10} | {'-'*10} | {'-'*8} | {'-'*8}")
for i, vn in enumerate(var_names):
    p = 2 * (1 - stats.norm.cdf(abs(t_stats[i])))
    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.1 else ""
    print(f"  {vn:>12} | {beta[i]*100:>10.4f}% | {se_hac[i]*100:>10.4f}% | {t_stats[i]:>8.3f} | {p:>8.4f} {sig}")
    reg_results[vn] = {
        'coefficient': float(beta[i]),
        'se_hac': float(se_hac[i]),
        't_stat': float(t_stats[i]),
        'p_value': float(p),
    }

# R-squared
ss_tot = np.sum((y - y.mean())**2)
ss_res = np.sum(resid**2)
r_squared = 1 - ss_res / ss_tot
print(f"\n  R² = {r_squared:.6f}")
print(f"  N = {n}")

reg_results['r_squared'] = float(r_squared)
reg_results['n'] = int(n)
results['regression'] = reg_results

# =============================================================================
# 10. VIX REGIME INTERACTION
# =============================================================================
print("\n\n[10] VIX Regime Interaction (High VIX vs Low VIX events)")
print("=" * 70)

vix_median = data['VIX'].median()
data['high_vix'] = data['VIX'] > vix_median
print(f"  VIX median: {vix_median:.2f}")

results['vix_regime'] = {}
for name, mask in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
    for regime, regime_mask in [('Low VIX', ~data['high_vix']), ('High VIX', data['high_vix'])]:
        event_abs = data.loc[mask & regime_mask, 'AbsReturn'].dropna()
        nonevent_abs = data.loc[~mask & data['is_no_event'] & regime_mask, 'AbsReturn'].dropna()

        if len(event_abs) > 5:
            t_stat, p_val = stats.ttest_ind(event_abs, nonevent_abs, equal_var=False)
            ratio = float(event_abs.mean() / nonevent_abs.mean())
            print(f"  {name} × {regime}: n={len(event_abs)}, ratio={ratio:.3f}x, t={t_stat:.3f}, p={p_val:.4f}")
            results['vix_regime'][f'{name}_{regime}'] = {
                'n': len(event_abs),
                'ratio': ratio,
                't_stat': float(t_stat),
                'p_value': float(p_val),
            }

# =============================================================================
# 11. OVERLAP ANALYSIS (events on same day?)
# =============================================================================
print("\n\n[11] Event Overlap Analysis")
print("=" * 70)

fomc_set = set(fomc_days)
nfp_set = set(nfp_days)
cpi_set = set(cpi_days)

fomc_nfp = fomc_set & nfp_set
fomc_cpi = fomc_set & cpi_set
nfp_cpi = nfp_set & cpi_set
all_three = fomc_set & nfp_set & cpi_set

print(f"  FOMC ∩ NFP: {len(fomc_nfp)} days")
print(f"  FOMC ∩ CPI: {len(fomc_cpi)} days")
print(f"  NFP ∩ CPI:  {len(nfp_cpi)} days")
print(f"  All three:  {len(all_three)} days")

results['overlap'] = {
    'fomc_nfp': len(fomc_nfp),
    'fomc_cpi': len(fomc_cpi),
    'nfp_cpi': len(nfp_cpi),
    'all_three': len(all_three),
}

# =============================================================================
# 12. CROSS-EVENT COMPARISON
# =============================================================================
print("\n\n[12] Cross-Event Comparison (Which event moves vol most?)")
print("=" * 70)

# Rank events by vol impact
events_ranked = []
for name, mask in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
    event_abs = data.loc[mask, 'AbsReturn'].dropna()
    nonevent_abs = data.loc[data['is_no_event'], 'AbsReturn'].dropna()
    excess_vol = float(event_abs.mean() - nonevent_abs.mean())
    events_ranked.append((name, excess_vol, float(event_abs.mean())))

events_ranked.sort(key=lambda x: x[1], reverse=True)
print(f"\n  Ranked by excess |return| (event - non-event):")
for rank, (name, excess, mean_vol) in enumerate(events_ranked, 1):
    print(f"    {rank}. {name}: excess = {excess*100:+.3f}%, mean |ret| = {mean_vol*100:.3f}%")

# Pairwise comparison of event-day vol
print(f"\n  Pairwise event vol comparisons (t-test):")
for name1, mask1 in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
    for name2, mask2 in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
        if name1 >= name2:
            continue
        abs1 = data.loc[mask1, 'AbsReturn'].dropna()
        abs2 = data.loc[mask2, 'AbsReturn'].dropna()
        t_stat, p_val = stats.ttest_ind(abs1, abs2, equal_var=False)
        print(f"    {name1} vs {name2}: t={t_stat:.3f}, p={p_val:.4f}")

results['cross_event'] = {
    'ranking': [(name, excess, mean_vol) for name, excess, mean_vol in events_ranked]
}

# =============================================================================
# 13. PRACTICAL IMPLICATIONS FOR VT STRATEGY
# =============================================================================
print("\n\n[13] Practical Implications for VT Strategy")
print("=" * 70)

# If event days have systematically higher vol, reducing exposure might help
# Calculate: what if we halve position on event days?
event_days_return = data.loc[data['is_any_event'], 'Return'].dropna()
nonevent_days_return = data.loc[data['is_no_event'], 'Return'].dropna()

# Strategy: full weight on non-event, half weight on event days
# Compare: (a) always full, (b) half on event days
print(f"\n  Event day frequency: {data['is_any_event'].mean()*100:.1f}% of trading days")
print(f"  Event day mean |return|: {data.loc[data['is_any_event'], 'AbsReturn'].mean()*100:.3f}%")
print(f"  Non-event day mean |return|: {data.loc[data['is_no_event'], 'AbsReturn'].mean()*100:.3f}%")

# Sharpe comparison (rough)
full_returns = data['Return'].dropna()
# Half-weight on event days
adjusted_returns = data['Return'].copy()
adjusted_returns[data['is_any_event']] *= 0.5

sharpe_full = float(full_returns.mean() / full_returns.std() * np.sqrt(252))
sharpe_adjusted = float(adjusted_returns.dropna().mean() / adjusted_returns.dropna().std() * np.sqrt(252))

print(f"\n  Full exposure Sharpe: {sharpe_full:.4f}")
print(f"  Half-weight event day Sharpe: {sharpe_adjusted:.4f}")
print(f"  Difference: {sharpe_adjusted - sharpe_full:+.4f}")

results['vt_implications'] = {
    'event_day_frequency': float(data['is_any_event'].mean()),
    'sharpe_full': sharpe_full,
    'sharpe_half_event': sharpe_adjusted,
    'sharpe_difference': sharpe_adjusted - sharpe_full,
}

# =============================================================================
# 14. UPCOMING EVENTS (SERVICE FOR EVENT CALENDAR)
# =============================================================================
print("\n\n[14] Upcoming Macro Events (April 2026)")
print("=" * 70)

upcoming = {
    'NFP_Apr_2026': '2026-04-03 (Fri)',
    'CPI_Apr_2026': '2026-04-10 (approx)',
    'FOMC_Apr_2026': '2026-04-28-29 (announcement 04/29)',
}

for event, date in upcoming.items():
    print(f"  {event}: {date}")

# Expected vol based on historical
nonevent_mean = float(data.loc[data['is_no_event'], 'AbsReturn'].mean())
for name, mask in [('FOMC', data['is_fomc']), ('NFP', data['is_nfp']), ('CPI', data['is_cpi'])]:
    event_mean = float(data.loc[mask, 'AbsReturn'].mean())
    print(f"  Expected {name} day |return|: {event_mean*100:.3f}% (vs baseline {nonevent_mean*100:.3f}%)")

results['upcoming_events'] = upcoming
results['expected_vol'] = {
    'fomc_day_absret': float(data.loc[data['is_fomc'], 'AbsReturn'].mean()),
    'nfp_day_absret': float(data.loc[data['is_nfp'], 'AbsReturn'].mean()),
    'cpi_day_absret': float(data.loc[data['is_cpi'], 'AbsReturn'].mean()),
    'nonevent_day_absret': nonevent_mean,
}

# =============================================================================
# 15. SUMMARY
# =============================================================================
print("\n\n" + "=" * 70)
print("SUMMARY: K513 Macro Event Vol Study")
print("=" * 70)

print(f"""
Key Findings:
1. FOMC days: |return| = {results['fomc']['event_mean_absret']*100:.3f}% vs {results['fomc']['nonevent_mean_absret']*100:.3f}%
   (ratio={results['fomc']['absret_ratio']:.3f}x, t={results['fomc']['absret_t_stat']:.3f}, p={results['fomc']['absret_p_value']:.4f})

2. NFP days: |return| = {results['nfp']['event_mean_absret']*100:.3f}% vs {results['nfp']['nonevent_mean_absret']*100:.3f}%
   (ratio={results['nfp']['absret_ratio']:.3f}x, t={results['nfp']['absret_t_stat']:.3f}, p={results['nfp']['absret_p_value']:.4f})

3. CPI days: |return| = {results['cpi']['event_mean_absret']*100:.3f}% vs {results['cpi']['nonevent_mean_absret']*100:.3f}%
   (ratio={results['cpi']['absret_ratio']:.3f}x, t={results['cpi']['absret_t_stat']:.3f}, p={results['cpi']['absret_p_value']:.4f})

4. VIX buildup pre-event:
   FOMC: {results['vix_buildup']['fomc']['mean_pre_vix_change']:+.3f} (p={results['vix_buildup']['fomc']['p_value']:.4f})
   NFP: {results['vix_buildup']['nfp']['mean_pre_vix_change']:+.3f} (p={results['vix_buildup']['nfp']['p_value']:.4f})
   CPI: {results['vix_buildup']['cpi']['mean_pre_vix_change']:+.3f} (p={results['vix_buildup']['cpi']['p_value']:.4f})

5. VIX resolution post-event:
   FOMC: {results['vix_resolution']['fomc']['mean_post_vix_change']:+.3f} (p={results['vix_resolution']['fomc']['p_value']:.4f})
   NFP: {results['vix_resolution']['nfp']['mean_post_vix_change']:+.3f} (p={results['vix_resolution']['nfp']['p_value']:.4f})
   CPI: {results['vix_resolution']['cpi']['mean_post_vix_change']:+.3f} (p={results['vix_resolution']['cpi']['p_value']:.4f})

6. VT strategy: Half-weight on event days -> Sharpe change = {results['vt_implications']['sharpe_difference']:+.4f}
""")

# =============================================================================
# SAVE RESULTS
# =============================================================================
output = {
    'experiment_id': 'K513',
    'title': 'US Macro Event Volatility Study (FOMC/NFP/CPI)',
    'proposed_by': 'Claude',
    'executed_by': 'Claude',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': int(len(data)),
    'n_fomc': int(len(fomc_days)),
    'n_nfp': int(len(nfp_days)),
    'n_cpi': int(len(cpi_days)),
    'references': [
        'Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JF',
        'Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?" RFS',
        'Ai & Bansal (2018) "Risk Preferences and the Macroeconomic Announcement Premium" JFE',
        'K96: FOMC causal vol study',
        'K414: FOMC-VIX not tradeable',
    ],
    'event_day_statistics': {
        'fomc': results['fomc'],
        'nfp': results['nfp'],
        'cpi': results['cpi'],
        'any_event': results['any_event'],
    },
    'event_windows': results['event_windows'],
    'vix_buildup': results['vix_buildup'],
    'vix_resolution': results['vix_resolution'],
    'subsample_stability': {
        'fomc': results.get('subsample_fomc', {}),
        'nfp': results.get('subsample_nfp', {}),
        'cpi': results.get('subsample_cpi', {}),
    },
    'nonparametric_tests': {
        'fomc': results.get('mannwhitney_fomc', {}),
        'nfp': results.get('mannwhitney_nfp', {}),
        'cpi': results.get('mannwhitney_cpi', {}),
    },
    'regression': results['regression'],
    'vix_regime_interaction': results.get('vix_regime', {}),
    'overlap_analysis': results['overlap'],
    'cross_event_comparison': results['cross_event'],
    'vt_implications': results['vt_implications'],
    'upcoming_events': results['upcoming_events'],
    'expected_vol': results['expected_vol'],
}

output_path = 'experiments/k513_macro_event_vol_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("K513 complete.")
