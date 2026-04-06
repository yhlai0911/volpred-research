"""
K925: CPI Announcement Volatility Event Study -- SPY
=====================================================
Builds on K513 (CPI 1.03x NS) with deeper CPI-focused analysis:
- BLS official CPI release dates (not approximation)
- CPI surprise proxy (deviation from trend)
- High-inflation vs low-inflation regime
- 12/VIX auto-adaptation on CPI days
- Bootstrap confidence intervals

References:
- Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JF
- Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?" RFS
- K513: FOMC/NFP/CPI event vol study (CPI 1.03x NS p=0.758)
- K773: CPI dates approximate bug identified by Codex
- K801: VIX shock guard NULL

Data: yfinance (SPY, ^VIX), FRED (CPIAUCSL)
Period: 2015-01 to 2026-03
"""

import json
import os
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ==============================================================================
# BLS Official CPI Release Dates (2015-2026)
# Source: Bureau of Labor Statistics release calendar
# CPI is released at 8:30 AM ET, usually 2nd or 3rd week of month
# These are actual release dates for the CPI-U monthly report
# ==============================================================================
CPI_RELEASE_DATES = [
    # 2015
    '2015-01-16', '2015-02-26', '2015-03-24', '2015-04-17', '2015-05-22',
    '2015-06-18', '2015-07-17', '2015-08-19', '2015-09-16', '2015-10-15',
    '2015-11-17', '2015-12-15',
    # 2016
    '2016-01-20', '2016-02-19', '2016-03-16', '2016-04-14', '2016-05-17',
    '2016-06-16', '2016-07-15', '2016-08-16', '2016-09-16', '2016-10-18',
    '2016-11-17', '2016-12-15',
    # 2017
    '2017-01-18', '2017-02-15', '2017-03-15', '2017-04-14', '2017-05-12',
    '2017-06-14', '2017-07-14', '2017-08-11', '2017-09-14', '2017-10-13',
    '2017-11-15', '2017-12-13',
    # 2018
    '2018-01-12', '2018-02-14', '2018-03-13', '2018-04-11', '2018-05-10',
    '2018-06-12', '2018-07-12', '2018-08-10', '2018-09-13', '2018-10-11',
    '2018-11-14', '2018-12-12',
    # 2019
    '2019-01-11', '2019-02-13', '2019-03-12', '2019-04-10', '2019-05-10',
    '2019-06-12', '2019-07-11', '2019-08-13', '2019-09-12', '2019-10-10',
    '2019-11-13', '2019-12-11',
    # 2020
    '2020-01-14', '2020-02-13', '2020-03-11', '2020-04-10', '2020-05-12',
    '2020-06-10', '2020-07-14', '2020-08-12', '2020-09-11', '2020-10-13',
    '2020-11-12', '2020-12-10',
    # 2021
    '2021-01-13', '2021-02-10', '2021-03-10', '2021-04-13', '2021-05-12',
    '2021-06-10', '2021-07-13', '2021-08-11', '2021-09-14', '2021-10-13',
    '2021-11-10', '2021-12-10',
    # 2022
    '2022-01-12', '2022-02-10', '2022-03-10', '2022-04-12', '2022-05-11',
    '2022-06-10', '2022-07-13', '2022-08-10', '2022-09-13', '2022-10-13',
    '2022-11-10', '2022-12-13',
    # 2023
    '2023-01-12', '2023-02-14', '2023-03-14', '2023-04-12', '2023-05-10',
    '2023-06-13', '2023-07-12', '2023-08-10', '2023-09-13', '2023-10-12',
    '2023-11-14', '2023-12-12',
    # 2024
    '2024-01-11', '2024-02-13', '2024-03-12', '2024-04-10', '2024-05-15',
    '2024-06-12', '2024-07-11', '2024-08-14', '2024-09-11', '2024-10-10',
    '2024-11-13', '2024-12-11',
    # 2025
    '2025-01-15', '2025-02-12', '2025-03-12', '2025-04-10', '2025-05-13',
    '2025-06-11', '2025-07-15', '2025-08-12', '2025-09-10', '2025-10-14',
    '2025-11-12', '2025-12-10',
    # 2026 (partial)
    '2026-01-14', '2026-02-11', '2026-03-11',
]

def download_data():
    """Download SPY, VIX, and CPI data."""
    print("Downloading SPY and VIX data...")
    spy = yf.download('SPY', start='2014-12-01', end='2026-04-01', progress=False)
    vix = yf.download('^VIX', start='2014-12-01', end='2026-04-01', progress=False)

    # Handle multi-level columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    # Handle column name: newer yfinance uses 'Close' (adjusted), older uses 'Adj Close'
    price_col = 'Adj Close' if 'Adj Close' in spy.columns else 'Close'
    vix_price_col = 'Adj Close' if 'Adj Close' in vix.columns else 'Close'

    # Calculate returns
    spy['Return'] = spy[price_col].pct_change()
    spy['AbsReturn'] = spy['Return'].abs()
    spy['LogReturn'] = np.log(spy[price_col] / spy[price_col].shift(1))

    # VIX close
    vix_close = vix[vix_price_col].rename('VIX')
    vix_change = vix_close.diff().rename('VIX_Change')

    # Merge
    df = spy[[price_col, 'Return', 'AbsReturn', 'LogReturn']].copy()
    df = df.rename(columns={price_col: 'Price'})
    df = df.join(vix_close).join(vix_change)
    df = df.dropna()

    # Filter to 2015+
    df = df[df.index >= '2015-01-01']

    print(f"Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, {len(df)} trading days")
    return df


def download_cpi_data():
    """Load CPI data from local FRED CSV or download from FRED."""
    print("Loading CPI data...")

    # Try local CSV first (already downloaded by collect macro scripts)
    local_path = os.path.join(os.path.dirname(OUTPUT_DIR), '..', 'storage', 'macro', 'fred_CPIAUCSL.csv')
    local_path = os.path.normpath(local_path)

    try:
        cpi = pd.read_csv(local_path, parse_dates=['observation_date'], index_col='observation_date')
        cpi.columns = ['CPI']
        # Drop rows with missing values
        cpi = cpi.dropna(subset=['CPI'])
        cpi['CPI'] = pd.to_numeric(cpi['CPI'], errors='coerce')
        cpi = cpi.dropna()
        cpi['CPI_MoM'] = cpi['CPI'].pct_change() * 100  # Monthly % change
        cpi['CPI_YoY'] = cpi['CPI'].pct_change(12) * 100  # YoY % change
        cpi['CPI_MoM_MA3'] = cpi['CPI_MoM'].rolling(3).mean()  # 3-month MA
        cpi['CPI_Surprise'] = cpi['CPI_MoM'] - cpi['CPI_MoM_MA3']  # Surprise proxy
        # Filter to relevant period
        cpi = cpi[cpi.index >= '2014-06-01']
        print(f"CPI data from local CSV: {len(cpi)} months ({cpi.index[0].strftime('%Y-%m')} to {cpi.index[-1].strftime('%Y-%m')})")
        return cpi
    except Exception as e:
        print(f"Local CPI load failed: {e}. Skipping CPI surprise analysis.")
        return None


def mark_cpi_days(df):
    """Mark CPI announcement days in the DataFrame."""
    cpi_dates = pd.to_datetime(CPI_RELEASE_DATES)

    # Match to trading days (find nearest trading day if CPI falls on non-trading day)
    matched_dates = []
    for cpi_date in cpi_dates:
        # Find the nearest trading day (same day or next trading day)
        mask = df.index >= cpi_date
        if mask.any():
            nearest = df.index[mask][0]
            # Only match if within 2 business days
            if (nearest - cpi_date).days <= 3:
                matched_dates.append(nearest)

    df['IsCPI'] = df.index.isin(matched_dates).astype(int)
    n_cpi = df['IsCPI'].sum()
    print(f"Matched {n_cpi} CPI release dates to trading days")
    return df, matched_dates


def event_day_analysis(df):
    """Compare CPI day vs non-CPI day statistics."""
    cpi_days = df[df['IsCPI'] == 1]
    non_cpi = df[df['IsCPI'] == 0]

    # Absolute return comparison
    cpi_absret = cpi_days['AbsReturn'].values
    non_absret = non_cpi['AbsReturn'].values

    absret_ratio = cpi_absret.mean() / non_absret.mean()
    t_stat, p_value = stats.ttest_ind(cpi_absret, non_absret, equal_var=False)

    # Mann-Whitney U test (non-parametric)
    u_stat, u_pval = stats.mannwhitneyu(cpi_absret, non_absret, alternative='two-sided')

    # VIX comparison
    cpi_vix = cpi_days['VIX'].values
    non_vix = non_cpi['VIX'].values
    vix_t, vix_p = stats.ttest_ind(cpi_vix, non_vix, equal_var=False)

    # VIX change on CPI day
    cpi_vix_change = cpi_days['VIX_Change'].values
    vix_chg_t, vix_chg_p = stats.ttest_1samp(cpi_vix_change, 0)

    # Mean return on CPI day (is it positive?)
    cpi_ret = cpi_days['Return'].values
    ret_t, ret_p = stats.ttest_1samp(cpi_ret, 0)

    # Bootstrap CI for absret ratio
    n_boot = 1000
    boot_ratios = []
    for _ in range(n_boot):
        boot_cpi = np.random.choice(cpi_absret, size=len(cpi_absret), replace=True)
        boot_non = np.random.choice(non_absret, size=len(non_absret), replace=True)
        boot_ratios.append(boot_cpi.mean() / boot_non.mean())
    boot_ci = np.percentile(boot_ratios, [2.5, 97.5])

    results = {
        'n_cpi_days': len(cpi_days),
        'n_non_cpi_days': len(non_cpi),
        'cpi_mean_absret': float(cpi_absret.mean()),
        'non_cpi_mean_absret': float(non_absret.mean()),
        'absret_ratio': float(absret_ratio),
        'absret_t_stat': float(t_stat),
        'absret_p_value': float(p_value),
        'absret_bootstrap_ci_2.5': float(boot_ci[0]),
        'absret_bootstrap_ci_97.5': float(boot_ci[1]),
        'mannwhitney_u': float(u_stat),
        'mannwhitney_p': float(u_pval),
        'cpi_mean_vix': float(cpi_vix.mean()),
        'non_cpi_mean_vix': float(non_vix.mean()),
        'vix_level_t_stat': float(vix_t),
        'vix_level_p_value': float(vix_p),
        'cpi_mean_vix_change': float(cpi_vix_change.mean()),
        'vix_change_t_stat': float(vix_chg_t),
        'vix_change_p_value': float(vix_chg_p),
        'cpi_mean_return': float(cpi_ret.mean()),
        'cpi_return_t_stat': float(ret_t),
        'cpi_return_p_value': float(ret_p),
        'cpi_std_return': float(cpi_ret.std()),
        'non_cpi_std_return': float(non_cpi['Return'].std()),
        'cpi_median_absret': float(np.median(cpi_absret)),
        'non_cpi_median_absret': float(np.median(non_absret)),
    }

    print(f"\n=== CPI Day vs Non-CPI Day ===")
    print(f"CPI days: {len(cpi_days)}, Non-CPI: {len(non_cpi)}")
    print(f"|Return| ratio: {absret_ratio:.4f} (CPI/Non-CPI)")
    print(f"  t-stat: {t_stat:.3f}, p-value: {p_value:.4f}")
    print(f"  Bootstrap 95% CI: [{boot_ci[0]:.4f}, {boot_ci[1]:.4f}]")
    print(f"  Mann-Whitney U p-value: {u_pval:.4f}")
    print(f"VIX on CPI day: {cpi_vix.mean():.2f} vs {non_vix.mean():.2f} (p={vix_p:.4f})")
    print(f"VIX change on CPI day: {cpi_vix_change.mean():.3f} (p={vix_chg_p:.4f})")
    print(f"Mean return on CPI day: {cpi_ret.mean()*100:.3f}% (p={ret_p:.4f})")

    return results


def event_window_analysis(df, matched_dates, window=5):
    """Analyze [-window, +window] around CPI days."""
    trading_dates = df.index.tolist()

    window_stats = {}
    for offset in range(-window, window + 1):
        absrets = []
        rets = []
        vix_changes = []
        vix_levels = []

        for cpi_date in matched_dates:
            if cpi_date not in trading_dates:
                continue
            idx = trading_dates.index(cpi_date)
            target_idx = idx + offset
            if 0 <= target_idx < len(trading_dates):
                target_date = trading_dates[target_idx]
                row = df.loc[target_date]
                absrets.append(row['AbsReturn'])
                rets.append(row['Return'])
                vix_changes.append(row['VIX_Change'])
                vix_levels.append(row['VIX'])

        window_stats[offset] = {
            'mean_abs_return': float(np.mean(absrets)),
            'median_abs_return': float(np.median(absrets)),
            'mean_return': float(np.mean(rets)),
            'mean_vix_change': float(np.mean(vix_changes)),
            'mean_vix_level': float(np.mean(vix_levels)),
            'std_return': float(np.std(rets)),
            'n': len(absrets),
        }

    # Print
    print(f"\n=== Event Window [-{window}, +{window}] ===")
    print(f"{'Day':>4}  {'|Ret| bp':>10}  {'Ret bp':>8}  {'DVIX':>8}  {'VIX':>6}  {'N':>4}")
    for offset in range(-window, window + 1):
        s = window_stats[offset]
        marker = " <-- CPI" if offset == 0 else ""
        print(f"{offset:>4}  {s['mean_abs_return']*10000:>10.1f}  {s['mean_return']*10000:>8.1f}  "
              f"{s['mean_vix_change']:>8.3f}  {s['mean_vix_level']:>6.1f}  {s['n']:>4}{marker}")

    return window_stats


def inflation_regime_analysis(df, cpi_data):
    """Compare CPI day effects in high-inflation vs low-inflation periods."""
    # Define regimes
    # Low inflation: 2015-2020 (CPI YoY < 3%)
    # High inflation: 2021-2023 (CPI YoY peaked at 9.1%)
    # Post-peak: 2024-2026 (CPI YoY falling from 3.4% to ~2.8%)

    regimes = {
        'low_inflation_2015_2020': ('2015-01-01', '2020-12-31'),
        'high_inflation_2021_2023': ('2021-01-01', '2023-12-31'),
        'post_peak_2024_2026': ('2024-01-01', '2026-12-31'),
    }

    results = {}
    for regime_name, (start, end) in regimes.items():
        mask = (df.index >= start) & (df.index <= end)
        regime_df = df[mask]

        cpi_days = regime_df[regime_df['IsCPI'] == 1]
        non_cpi = regime_df[regime_df['IsCPI'] == 0]

        if len(cpi_days) < 5:
            continue

        cpi_absret = cpi_days['AbsReturn'].values
        non_absret = non_cpi['AbsReturn'].values

        ratio = cpi_absret.mean() / non_absret.mean() if non_absret.mean() > 0 else np.nan
        t_stat, p_val = stats.ttest_ind(cpi_absret, non_absret, equal_var=False)

        # CPI YoY range in this period
        if cpi_data is not None:
            cpi_mask = (cpi_data.index >= start) & (cpi_data.index <= end)
            cpi_yoy = cpi_data.loc[cpi_mask, 'CPI_YoY']
            yoy_range = f"{cpi_yoy.min():.1f}% - {cpi_yoy.max():.1f}%" if len(cpi_yoy) > 0 else "N/A"
        else:
            yoy_range = "N/A"

        results[regime_name] = {
            'n_cpi_days': len(cpi_days),
            'n_non_cpi_days': len(non_cpi),
            'cpi_mean_absret': float(cpi_absret.mean()),
            'non_cpi_mean_absret': float(non_absret.mean()),
            'absret_ratio': float(ratio),
            't_stat': float(t_stat),
            'p_value': float(p_val),
            'cpi_yoy_range': yoy_range,
            'cpi_mean_return': float(cpi_days['Return'].mean()),
            'cpi_std_return': float(cpi_days['Return'].std()),
        }

        print(f"\n--- {regime_name} (CPI YoY: {yoy_range}) ---")
        print(f"  N CPI days: {len(cpi_days)}")
        print(f"  |Ret| ratio: {ratio:.4f} (t={t_stat:.3f}, p={p_val:.4f})")
        print(f"  CPI day mean ret: {cpi_days['Return'].mean()*100:.3f}%")

    return results


def cpi_surprise_analysis(df, cpi_data, matched_dates):
    """Analyze market reaction conditional on CPI surprise direction."""
    if cpi_data is None:
        print("\nSkipping CPI surprise analysis (no FRED data)")
        return None

    # Map each CPI release date to its surprise
    results = {'positive_surprise': [], 'negative_surprise': [], 'neutral': []}

    for cpi_date in matched_dates:
        if cpi_date not in df.index:
            continue

        # Find the CPI data month that was released on this date
        # CPI released in month M reports data for month M-1
        release_month = cpi_date.to_period('M')
        data_month = release_month - 1

        # Find surprise for this data month
        surprise_mask = cpi_data.index.to_period('M') == data_month
        if surprise_mask.sum() == 0:
            continue

        surprise = cpi_data.loc[surprise_mask, 'CPI_Surprise'].values[0]
        if np.isnan(surprise):
            continue

        day_data = {
            'date': cpi_date.strftime('%Y-%m-%d'),
            'return': float(df.loc[cpi_date, 'Return']),
            'abs_return': float(df.loc[cpi_date, 'AbsReturn']),
            'vix_change': float(df.loc[cpi_date, 'VIX_Change']),
            'surprise': float(surprise),
        }

        if surprise > 0.05:  # Hot CPI (above trend)
            results['positive_surprise'].append(day_data)
        elif surprise < -0.05:  # Cool CPI (below trend)
            results['negative_surprise'].append(day_data)
        else:
            results['neutral'].append(day_data)

    # Analyze
    summary = {}
    for category in ['positive_surprise', 'negative_surprise', 'neutral']:
        if len(results[category]) < 3:
            continue
        rets = [d['return'] for d in results[category]]
        absrets = [d['abs_return'] for d in results[category]]
        vix_chgs = [d['vix_change'] for d in results[category]]

        summary[category] = {
            'n': len(results[category]),
            'mean_return': float(np.mean(rets)),
            'mean_abs_return': float(np.mean(absrets)),
            'mean_vix_change': float(np.mean(vix_chgs)),
            'std_return': float(np.std(rets)),
            'median_abs_return': float(np.median(absrets)),
        }

    # Test: hot CPI vs cool CPI
    if 'positive_surprise' in summary and 'negative_surprise' in summary:
        hot_absrets = [d['abs_return'] for d in results['positive_surprise']]
        cool_absrets = [d['abs_return'] for d in results['negative_surprise']]
        t_hot_cool, p_hot_cool = stats.ttest_ind(hot_absrets, cool_absrets, equal_var=False)

        hot_rets = [d['return'] for d in results['positive_surprise']]
        cool_rets = [d['return'] for d in results['negative_surprise']]
        t_ret, p_ret = stats.ttest_ind(hot_rets, cool_rets, equal_var=False)

        summary['hot_vs_cool_absret_t'] = float(t_hot_cool)
        summary['hot_vs_cool_absret_p'] = float(p_hot_cool)
        summary['hot_vs_cool_return_t'] = float(t_ret)
        summary['hot_vs_cool_return_p'] = float(p_ret)

        print(f"\n=== CPI Surprise Analysis ===")
        print(f"Hot CPI (above trend): n={summary['positive_surprise']['n']}, "
              f"|ret|={summary['positive_surprise']['mean_abs_return']*10000:.1f}bp, "
              f"ret={summary['positive_surprise']['mean_return']*10000:.1f}bp")
        print(f"Cool CPI (below trend): n={summary['negative_surprise']['n']}, "
              f"|ret|={summary['negative_surprise']['mean_abs_return']*10000:.1f}bp, "
              f"ret={summary['negative_surprise']['mean_return']*10000:.1f}bp")
        if 'neutral' in summary:
            print(f"Neutral CPI: n={summary['neutral']['n']}, "
                  f"|ret|={summary['neutral']['mean_abs_return']*10000:.1f}bp")
        print(f"Hot vs Cool |ret| t-test: t={t_hot_cool:.3f}, p={p_hot_cool:.4f}")
        print(f"Hot vs Cool return t-test: t={t_ret:.3f}, p={p_ret:.4f}")

    return summary


def vix_pre_post_analysis(df, matched_dates, pre_window=5, post_window=5):
    """Analyze VIX behavior before and after CPI announcements."""
    trading_dates = df.index.tolist()

    pre_vix_changes = []
    post_vix_changes = []

    for cpi_date in matched_dates:
        if cpi_date not in trading_dates:
            continue
        idx = trading_dates.index(cpi_date)

        # Pre-CPI: VIX change from day-(pre_window) to day-1
        pre_start_idx = idx - pre_window
        pre_end_idx = idx - 1
        if pre_start_idx >= 0 and pre_end_idx >= 0:
            pre_vix_start = df.loc[trading_dates[pre_start_idx], 'VIX']
            pre_vix_end = df.loc[trading_dates[pre_end_idx], 'VIX']
            pre_vix_changes.append(pre_vix_end - pre_vix_start)

        # Post-CPI: VIX change from day 0 to day+(post_window)
        post_end_idx = idx + post_window
        if post_end_idx < len(trading_dates):
            post_vix_start = df.loc[cpi_date, 'VIX']
            post_vix_end = df.loc[trading_dates[post_end_idx], 'VIX']
            post_vix_changes.append(post_vix_end - post_vix_start)

    pre_arr = np.array(pre_vix_changes)
    post_arr = np.array(post_vix_changes)

    pre_t, pre_p = stats.ttest_1samp(pre_arr, 0)
    post_t, post_p = stats.ttest_1samp(post_arr, 0)

    results = {
        'pre_cpi_vix_change': {
            'mean': float(pre_arr.mean()),
            'median': float(np.median(pre_arr)),
            'std': float(pre_arr.std()),
            't_stat': float(pre_t),
            'p_value': float(pre_p),
            'pct_positive': float((pre_arr > 0).mean()),
            'n': len(pre_arr),
        },
        'post_cpi_vix_change': {
            'mean': float(post_arr.mean()),
            'median': float(np.median(post_arr)),
            'std': float(post_arr.std()),
            't_stat': float(post_t),
            'p_value': float(post_p),
            'pct_negative': float((post_arr < 0).mean()),
            'n': len(post_arr),
        },
    }

    print(f"\n=== VIX Pre/Post CPI ===")
    print(f"Pre-CPI ({pre_window}d): mean DVIX = {pre_arr.mean():.3f} "
          f"(t={pre_t:.3f}, p={pre_p:.4f}), {(pre_arr > 0).mean()*100:.0f}% positive")
    print(f"Post-CPI ({post_window}d): mean DVIX = {post_arr.mean():.3f} "
          f"(t={post_t:.3f}, p={post_p:.4f}), {(post_arr < 0).mean()*100:.0f}% negative")

    # Hypothesis: uncertainty resolution pattern (VIX up before, down after)
    is_resolution = pre_arr.mean() > 0 and post_arr.mean() < 0
    print(f"Uncertainty resolution pattern (VIX up pre, down post): {'YES' if is_resolution else 'NO'}")

    results['uncertainty_resolution'] = is_resolution
    return results


def twelve_vix_analysis(df, matched_dates):
    """Analyze how 12/VIX strategy naturally behaves around CPI days."""
    trading_dates = df.index.tolist()

    # Calculate 12/VIX weight (capped at 1.0)
    df['Weight_12VIX'] = np.minimum(12.0 / df['VIX'], 1.0)

    # Weight on CPI days vs non-CPI days
    cpi_weights = df.loc[df['IsCPI'] == 1, 'Weight_12VIX']
    non_cpi_weights = df.loc[df['IsCPI'] == 0, 'Weight_12VIX']

    t_w, p_w = stats.ttest_ind(cpi_weights.values, non_cpi_weights.values, equal_var=False)

    # Weight trajectory around CPI [-5, +5]
    weight_trajectory = {}
    for offset in range(-5, 6):
        weights = []
        for cpi_date in matched_dates:
            if cpi_date not in trading_dates:
                continue
            idx = trading_dates.index(cpi_date)
            target_idx = idx + offset
            if 0 <= target_idx < len(trading_dates):
                weights.append(df.loc[trading_dates[target_idx], 'Weight_12VIX'])
        weight_trajectory[offset] = float(np.mean(weights))

    # Compare 12/VIX portfolio return on CPI day vs non-CPI day
    # Using lagged weight (signal.shift(1)) -- weight from yesterday, return today
    df['Weight_Lagged'] = df['Weight_12VIX'].shift(1)
    df['PortRet'] = df['Weight_Lagged'] * df['Return']

    cpi_portret = df.loc[df['IsCPI'] == 1, 'PortRet'].dropna()
    non_portret = df.loc[df['IsCPI'] == 0, 'PortRet'].dropna()

    results = {
        'cpi_day_mean_weight': float(cpi_weights.mean()),
        'non_cpi_day_mean_weight': float(non_cpi_weights.mean()),
        'weight_diff_t_stat': float(t_w),
        'weight_diff_p_value': float(p_w),
        'weight_trajectory': {str(k): v for k, v in weight_trajectory.items()},
        'cpi_day_mean_portret': float(cpi_portret.mean()),
        'non_cpi_mean_portret': float(non_portret.mean()),
        'auto_derisking': float(cpi_weights.mean()) < float(non_cpi_weights.mean()),
    }

    print(f"\n=== 12/VIX Auto-Adaptation ===")
    print(f"Mean weight on CPI day: {cpi_weights.mean():.4f}")
    print(f"Mean weight on non-CPI day: {non_cpi_weights.mean():.4f}")
    print(f"Weight difference t-test: t={t_w:.3f}, p={p_w:.4f}")
    print(f"Auto de-risking: {'Yes' if results['auto_derisking'] else 'No'}")
    print(f"Portfolio return CPI day: {cpi_portret.mean()*10000:.1f}bp")
    print(f"Portfolio return non-CPI: {non_portret.mean()*10000:.1f}bp")

    return results


def plot_event_window(window_stats, output_dir):
    """Plot event window [-5, +5] around CPI days."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('K925: CPI Announcement Event Window [-5, +5]', fontsize=14, fontweight='bold')

    offsets = sorted(window_stats.keys())

    # 1. Mean |Return| (bp)
    ax = axes[0, 0]
    absrets = [window_stats[o]['mean_abs_return'] * 10000 for o in offsets]
    colors = ['#e74c3c' if o == 0 else '#3498db' for o in offsets]
    ax.bar(offsets, absrets, color=colors, alpha=0.8, edgecolor='white')
    ax.axhline(y=np.mean(absrets), color='gray', linestyle='--', alpha=0.5, label='Window avg')
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Mean |Return| (bp)')
    ax.set_title('Absolute Return')
    ax.legend()
    ax.set_xticks(offsets)

    # 2. Mean Return (bp)
    ax = axes[0, 1]
    rets = [window_stats[o]['mean_return'] * 10000 for o in offsets]
    colors_ret = ['#e74c3c' if r < 0 else '#27ae60' for r in rets]
    ax.bar(offsets, rets, color=colors_ret, alpha=0.8, edgecolor='white')
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Mean Return (bp)')
    ax.set_title('Signed Return')
    ax.set_xticks(offsets)

    # 3. VIX Change
    ax = axes[1, 0]
    vix_chg = [window_stats[o]['mean_vix_change'] for o in offsets]
    colors_vix = ['#e74c3c' if v > 0 else '#27ae60' for v in vix_chg]
    ax.bar(offsets, vix_chg, color=colors_vix, alpha=0.8, edgecolor='white')
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Mean VIX Change')
    ax.set_title('VIX Change')
    ax.set_xticks(offsets)

    # 4. VIX Level
    ax = axes[1, 1]
    vix_lvl = [window_stats[o]['mean_vix_level'] for o in offsets]
    ax.plot(offsets, vix_lvl, 'o-', color='#9b59b6', markersize=6, linewidth=2)
    ax.axvline(x=0, color='red', linestyle='--', alpha=0.5, label='CPI Day')
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Mean VIX Level')
    ax.set_title('VIX Level')
    ax.legend()
    ax.set_xticks(offsets)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k925_event_window.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_cpi_vs_normal(df, output_dir):
    """Plot CPI day vs non-CPI day volatility comparison."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('K925: CPI Day vs Non-CPI Day Comparison', fontsize=14, fontweight='bold')

    cpi_days = df[df['IsCPI'] == 1]
    non_cpi = df[df['IsCPI'] == 0]

    # 1. Distribution of |Return|
    ax = axes[0]
    bins = np.linspace(0, 0.04, 40)
    ax.hist(non_cpi['AbsReturn'], bins=bins, alpha=0.5, density=True, label=f'Non-CPI (n={len(non_cpi)})', color='#3498db')
    ax.hist(cpi_days['AbsReturn'], bins=bins, alpha=0.6, density=True, label=f'CPI (n={len(cpi_days)})', color='#e74c3c')
    ax.set_xlabel('|Return|')
    ax.set_ylabel('Density')
    ax.set_title('Distribution of |Return|')
    ax.legend()

    # 2. Box plot
    ax = axes[1]
    data_box = [non_cpi['AbsReturn'].values * 10000, cpi_days['AbsReturn'].values * 10000]
    bp = ax.boxplot(data_box, labels=['Non-CPI', 'CPI Day'], patch_artist=True,
                     showfliers=False)
    bp['boxes'][0].set_facecolor('#3498db')
    bp['boxes'][1].set_facecolor('#e74c3c')
    for box in bp['boxes']:
        box.set_alpha(0.6)
    ax.set_ylabel('|Return| (bp)')
    ax.set_title('|Return| Distribution')

    # 3. Bar chart: summary stats
    ax = axes[2]
    categories = ['Mean |Ret|\n(bp)', 'Median |Ret|\n(bp)', 'Std Return\n(bp)']
    non_vals = [
        non_cpi['AbsReturn'].mean() * 10000,
        non_cpi['AbsReturn'].median() * 10000,
        non_cpi['Return'].std() * 10000,
    ]
    cpi_vals = [
        cpi_days['AbsReturn'].mean() * 10000,
        cpi_days['AbsReturn'].median() * 10000,
        cpi_days['Return'].std() * 10000,
    ]
    x = np.arange(len(categories))
    w = 0.35
    ax.bar(x - w/2, non_vals, w, label='Non-CPI', color='#3498db', alpha=0.7)
    ax.bar(x + w/2, cpi_vals, w, label='CPI', color='#e74c3c', alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(categories)
    ax.set_ylabel('Basis Points')
    ax.set_title('Summary Statistics')
    ax.legend()

    plt.tight_layout()
    path = os.path.join(output_dir, 'k925_cpi_vs_normal.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_vix_around_cpi(window_stats, vix_pre_post, twelve_vix_results, output_dir):
    """Plot VIX behavior around CPI announcements."""
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    fig.suptitle('K925: VIX and 12/VIX Around CPI Announcements', fontsize=14, fontweight='bold')

    offsets = sorted(window_stats.keys())

    # 1. VIX level around CPI
    ax = axes[0]
    vix_levels = [window_stats[o]['mean_vix_level'] for o in offsets]
    ax.plot(offsets, vix_levels, 'o-', color='#9b59b6', markersize=8, linewidth=2)
    ax.fill_between(offsets, min(vix_levels) - 0.1, vix_levels, alpha=0.1, color='#9b59b6')
    ax.axvline(x=0, color='red', linestyle='--', alpha=0.5)
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Mean VIX')
    ax.set_title('VIX Level Around CPI')
    ax.set_xticks(offsets)

    # 2. Cumulative VIX change
    ax = axes[1]
    vix_changes = [window_stats[o]['mean_vix_change'] for o in offsets]
    cum_vix = np.cumsum(vix_changes)
    ax.plot(offsets, cum_vix, 's-', color='#e67e22', markersize=6, linewidth=2)
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.axvline(x=0, color='red', linestyle='--', alpha=0.5)
    ax.set_xlabel('Days relative to CPI')
    ax.set_ylabel('Cumulative Mean VIX Change')
    ax.set_title('Cumulative VIX Change')
    ax.set_xticks(offsets)

    # 3. 12/VIX weight trajectory
    ax = axes[2]
    if twelve_vix_results and 'weight_trajectory' in twelve_vix_results:
        traj = twelve_vix_results['weight_trajectory']
        traj_offsets = sorted([int(k) for k in traj.keys()])
        weights = [traj[str(o)] for o in traj_offsets]
        ax.plot(traj_offsets, weights, 'D-', color='#2ecc71', markersize=6, linewidth=2)
        ax.axvline(x=0, color='red', linestyle='--', alpha=0.5)
        ax.set_xlabel('Days relative to CPI')
        ax.set_ylabel('Mean 12/VIX Weight')
        ax.set_title('12/VIX Weight Around CPI')
        ax.set_xticks(traj_offsets)

    plt.tight_layout()
    path = os.path.join(output_dir, 'k925_vix_around_cpi.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def plot_regime_comparison(regime_results, output_dir):
    """Plot inflation regime comparison."""
    if not regime_results:
        return None

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    fig.suptitle('K925: CPI Day Effect by Inflation Regime', fontsize=14, fontweight='bold')

    names = list(regime_results.keys())
    short_names = [n.replace('_', '\n').replace('inflation\n', '') for n in names]
    ratios = [regime_results[n]['absret_ratio'] for n in names]
    p_values = [regime_results[n]['p_value'] for n in names]

    # 1. |Return| ratio by regime
    ax = axes[0]
    colors = ['#27ae60' if p < 0.05 else '#e74c3c' for p in p_values]
    bars = ax.bar(range(len(names)), ratios, color=colors, alpha=0.7, edgecolor='white')
    ax.axhline(y=1.0, color='black', linestyle='--', linewidth=1)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(short_names, fontsize=9)
    ax.set_ylabel('|Return| Ratio (CPI/Non-CPI)')
    ax.set_title('Volatility Amplification')
    for i, (r, p) in enumerate(zip(ratios, p_values)):
        sig = '*' if p < 0.05 else 'NS'
        ax.text(i, r + 0.01, f'{r:.3f}\n({sig})', ha='center', fontsize=9)

    # 2. CPI day mean return by regime
    ax = axes[1]
    rets = [regime_results[n]['cpi_mean_return'] * 10000 for n in names]
    colors_ret = ['#27ae60' if r > 0 else '#e74c3c' for r in rets]
    ax.bar(range(len(names)), rets, color=colors_ret, alpha=0.7, edgecolor='white')
    ax.axhline(y=0, color='black', linewidth=0.5)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(short_names, fontsize=9)
    ax.set_ylabel('Mean Return on CPI Day (bp)')
    ax.set_title('CPI Day Return Direction')

    plt.tight_layout()
    path = os.path.join(output_dir, 'k925_regime_comparison.png')
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Saved: {path}")
    return path


def main():
    print("=" * 70)
    print("K925: CPI Announcement Volatility Event Study -- SPY")
    print("=" * 70)

    # Step 1: Download data
    df = download_data()
    cpi_data = download_cpi_data()

    # Step 2: Mark CPI days
    df, matched_dates = mark_cpi_days(df)

    # Step 3: Event day analysis
    event_stats = event_day_analysis(df)

    # Step 4: Event window analysis
    window_stats = event_window_analysis(df, matched_dates, window=5)

    # Step 5: Inflation regime analysis
    regime_results = inflation_regime_analysis(df, cpi_data)

    # Step 6: CPI surprise analysis
    surprise_results = cpi_surprise_analysis(df, cpi_data, matched_dates)

    # Step 7: VIX pre/post analysis
    vix_results = vix_pre_post_analysis(df, matched_dates)

    # Step 8: 12/VIX auto-adaptation
    twelve_vix = twelve_vix_analysis(df, matched_dates)

    # Step 9: Generate plots
    print("\n=== Generating Plots ===")
    plot_event_window(window_stats, OUTPUT_DIR)
    plot_cpi_vs_normal(df, OUTPUT_DIR)
    plot_vix_around_cpi(window_stats, vix_results, twelve_vix, OUTPUT_DIR)
    plot_regime_comparison(regime_results, OUTPUT_DIR)

    # Step 10: Compile results
    # Key finding summary
    key_findings = []

    # 1. Overall CPI effect
    if event_stats['absret_p_value'] > 0.05:
        key_findings.append(f"CPI day |return| ratio = {event_stats['absret_ratio']:.3f}x "
                           f"(NS, p={event_stats['absret_p_value']:.3f}). "
                           f"Confirms K513 null result with official BLS dates.")
    else:
        key_findings.append(f"CPI day |return| ratio = {event_stats['absret_ratio']:.3f}x "
                           f"(sig, p={event_stats['absret_p_value']:.3f}).")

    # 2. Regime effect
    if regime_results:
        high_inf = regime_results.get('high_inflation_2021_2023', {})
        low_inf = regime_results.get('low_inflation_2015_2020', {})
        if high_inf and low_inf:
            key_findings.append(
                f"High-inflation era (2021-2023): CPI |ret| ratio = {high_inf.get('absret_ratio', 0):.3f}x "
                f"(p={high_inf.get('p_value', 1):.3f}) vs "
                f"low-inflation (2015-2020): {low_inf.get('absret_ratio', 0):.3f}x "
                f"(p={low_inf.get('p_value', 1):.3f})."
            )

    # 3. VIX uncertainty resolution
    if vix_results:
        key_findings.append(
            f"VIX uncertainty resolution pattern: "
            f"{'Supported' if vix_results.get('uncertainty_resolution', False) else 'NOT supported'}. "
            f"Pre-CPI DVIX = {vix_results['pre_cpi_vix_change']['mean']:.3f} "
            f"(p={vix_results['pre_cpi_vix_change']['p_value']:.3f}), "
            f"Post-CPI DVIX = {vix_results['post_cpi_vix_change']['mean']:.3f} "
            f"(p={vix_results['post_cpi_vix_change']['p_value']:.3f})."
        )

    # 4. 12/VIX auto-adaptation
    if twelve_vix:
        key_findings.append(
            f"12/VIX auto de-risking: {'Yes' if twelve_vix['auto_derisking'] else 'No'}. "
            f"CPI day weight = {twelve_vix['cpi_day_mean_weight']:.4f} vs "
            f"non-CPI = {twelve_vix['non_cpi_day_mean_weight']:.4f} "
            f"(p={twelve_vix['weight_diff_p_value']:.3f})."
        )

    # 5. CPI surprise
    if surprise_results and 'positive_surprise' in surprise_results and 'negative_surprise' in surprise_results:
        key_findings.append(
            f"Hot CPI (above trend): |ret| = {surprise_results['positive_surprise']['mean_abs_return']*10000:.0f}bp, "
            f"Cool CPI: |ret| = {surprise_results['negative_surprise']['mean_abs_return']*10000:.0f}bp "
            f"(p={surprise_results.get('hot_vs_cool_absret_p', 1):.3f})."
        )

    key_findings_str = ' '.join(key_findings)

    results = {
        'experiment_id': 'K925',
        'title': 'CPI Announcement Volatility Event Study -- SPY',
        'proposed_by': 'Claude (event calendar)',
        'executed_by': 'Claude',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (SPY, ^VIX), FRED (CPIAUCSL)',
        'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'n_trading_days': len(df),
        'n_cpi_days': event_stats['n_cpi_days'],
        'references': [
            'Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JF',
            'Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?" RFS',
            'K513: FOMC/NFP/CPI macro event vol study',
            'K773: CPI date approximation bug',
            'K801: VIX shock guard NULL',
        ],
        'cpi_release_date_source': 'BLS official schedule (manually compiled)',
        'event_day_statistics': event_stats,
        'event_window': {str(k): v for k, v in window_stats.items()},
        'inflation_regime_comparison': regime_results,
        'cpi_surprise_analysis': surprise_results,
        'vix_pre_post_cpi': vix_results,
        'twelve_vix_auto_adaptation': twelve_vix,
        'key_findings': key_findings_str,
        'plots': [
            'k925_event_window.png',
            'k925_cpi_vs_normal.png',
            'k925_vix_around_cpi.png',
            'k925_regime_comparison.png',
        ],
    }

    # Save results
    results_path = os.path.join(OUTPUT_DIR, 'k925_cpi_event_vol_results.json')
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved: {results_path}")

    print(f"\n{'=' * 70}")
    print("KEY FINDINGS:")
    print('=' * 70)
    for i, finding in enumerate(key_findings, 1):
        print(f"{i}. {finding}")
    print('=' * 70)

    return results


if __name__ == '__main__':
    main()
