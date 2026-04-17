"""
K410: Has Algorithmic Trading Changed Market Dynamics?
======================================================
Measuring the AI/Algo Footprint on US Equity Markets (2000-2024)

This is a MARKET MICROSTRUCTURE study — no vol prediction, no GARCH, no overlays.

Background:
  Algorithmic trading now accounts for 60-80% of US equity volume.
  Has this fundamentally changed how markets behave?

Data source: yfinance (SPY daily + intraday where available)
Period: 2000-01-01 to 2024-12-31 (25 years)

Analyses:
  1. Market efficiency evolution (rolling autocorrelation)
  2. Flash crash frequency (large intraday range, close near open)
  3. Volatility at different timescales (daily vs intraday ratio)
  4. Opening auction dynamics (first 30 min vs rest of day)
  5. End-of-day dynamics (last 30 min contribution)

Author: VolPred Research System (K410)
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import warnings
warnings.filterwarnings('ignore')

# ============================================================
# Data Collection
# ============================================================

def download_daily_data():
    """Download SPY daily data 2000-2024."""
    print("=" * 70)
    print("K410: Has Algorithmic Trading Changed Market Dynamics?")
    print("=" * 70)
    print("\n[1] Downloading SPY daily data (2000-2024)...")

    spy = yf.download("SPY", start="2000-01-01", end="2025-01-01", auto_adjust=True)

    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy.index = pd.to_datetime(spy.index)
    if spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    spy['Return'] = spy['Close'].pct_change()
    spy['LogReturn'] = np.log(spy['Close'] / spy['Close'].shift(1))
    spy['IntradayRange'] = (spy['High'] - spy['Low']) / spy['Open']
    spy['BodyRatio'] = abs(spy['Close'] - spy['Open']) / (spy['High'] - spy['Low'] + 1e-10)
    spy['GapReturn'] = spy['Open'] / spy['Close'].shift(1) - 1
    spy['IntradayReturn'] = spy['Close'] / spy['Open'] - 1
    spy = spy.dropna()

    print(f"  Downloaded {len(spy)} trading days: {spy.index[0].date()} to {spy.index[-1].date()}")
    return spy


# ============================================================
# Analysis 1: Market Efficiency Evolution
# ============================================================

def analyze_market_efficiency(spy):
    """Rolling autocorrelation of returns — lower ACF = more efficient."""
    print("\n" + "=" * 70)
    print("[Analysis 1] Market Efficiency Evolution (Rolling Autocorrelation)")
    print("=" * 70)

    results = {}

    # Rolling ACF(1) with 252-day window
    window = 252
    acf1_series = spy['Return'].rolling(window).apply(
        lambda x: pd.Series(x).autocorr(lag=1), raw=False
    )

    # Also compute ACF(1) for absolute returns (measures vol clustering persistence)
    acf1_abs_series = spy['Return'].abs().rolling(window).apply(
        lambda x: pd.Series(x).autocorr(lag=1), raw=False
    )

    # Define eras
    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    print(f"\n  Rolling ACF(1) of daily returns (window={window} days):")
    print(f"  {'Era':<30} {'Mean ACF(1)':>12} {'Std':>10} {'|ACF|>0.05 %':>14} {'Mean |ACF| abs ret':>20}")
    print(f"  {'-'*86}")

    era_results = {}
    for era_name, (start, end) in eras.items():
        mask = (acf1_series.index >= start) & (acf1_series.index <= end)
        acf_era = acf1_series[mask].dropna()
        acf_abs_era = acf1_abs_series[mask].dropna()

        if len(acf_era) == 0:
            continue

        mean_acf = acf_era.mean()
        std_acf = acf_era.std()
        pct_significant = (acf_era.abs() > 0.05).mean() * 100
        mean_abs_acf = acf_abs_era.mean()

        era_results[era_name] = {
            'mean_acf1': round(float(mean_acf), 4),
            'std_acf1': round(float(std_acf), 4),
            'pct_significant': round(float(pct_significant), 1),
            'mean_acf1_abs_returns': round(float(mean_abs_acf), 4),
        }
        print(f"  {era_name:<30} {mean_acf:>12.4f} {std_acf:>10.4f} {pct_significant:>13.1f}% {mean_abs_acf:>20.4f}")

    # Trend test: is ACF(1) declining over time?
    yearly_acf = acf1_series.resample('YE').mean().dropna()
    years_numeric = np.arange(len(yearly_acf))
    slope, intercept, r_value, p_value, std_err = stats.linregress(years_numeric, yearly_acf.values)

    results['era_comparison'] = era_results
    results['trend'] = {
        'slope_per_year': round(float(slope), 6),
        'r_squared': round(float(r_value**2), 4),
        'p_value': round(float(p_value), 4),
        'interpretation': 'declining' if slope < 0 else 'increasing',
    }

    print(f"\n  Trend in annual mean ACF(1):")
    print(f"    Slope: {slope:.6f}/year (p={p_value:.4f})")
    print(f"    R²: {r_value**2:.4f}")
    print(f"    Direction: {'Markets becoming more efficient' if slope < 0 else 'No clear efficiency trend'}")

    # Variance ratio test by era
    print(f"\n  Variance Ratio Test (VR(5) — weekly vs daily):")
    print(f"  {'Era':<30} {'VR(5)':>10} {'z-stat':>10} {'p-value':>10}")
    print(f"  {'-'*60}")

    vr_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ret_era = spy.loc[mask, 'Return'].dropna()

        if len(ret_era) < 50:
            continue

        # Variance ratio: Var(q-period return) / (q * Var(1-period return))
        q = 5
        ret_q = ret_era.rolling(q).sum().dropna()
        vr = ret_q.var() / (q * ret_era.var())

        # Lo-MacKinlay z-stat (simplified)
        n = len(ret_era)
        z_stat = (vr - 1) / np.sqrt(2 * (q - 1) / n)
        p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))

        vr_results[era_name] = {
            'vr5': round(float(vr), 4),
            'z_stat': round(float(z_stat), 4),
            'p_value': round(float(p_val), 4),
        }
        print(f"  {era_name:<30} {vr:>10.4f} {z_stat:>10.4f} {p_val:>10.4f}")

    results['variance_ratio'] = vr_results

    return results


# ============================================================
# Analysis 2: Flash Crash Frequency
# ============================================================

def analyze_flash_crashes(spy):
    """Identify flash-crash-like events: large intraday range but close near open."""
    print("\n" + "=" * 70)
    print("[Analysis 2] Flash Crash / Intraday Reversal Frequency")
    print("=" * 70)

    results = {}

    # Define flash-crash-like event:
    # Intraday range > 3% AND body ratio < 0.3 (close near open = reversal)
    spy['IsFlashCrashLike'] = (spy['IntradayRange'] > 0.03) & (spy['BodyRatio'] < 0.30)

    # Also track: large intraday range days (>2%) regardless of reversal
    spy['LargeRange'] = spy['IntradayRange'] > 0.02

    # V-shaped intraday: large range, close > open but low was much lower
    spy['VShape'] = (
        (spy['IntradayRange'] > 0.02) &
        ((spy['Low'] - spy['Open']) / spy['Open'] < -0.01) &
        (spy['Close'] > spy['Open'])
    )

    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    print(f"\n  Flash-crash-like events (range>3%, close near open):")
    print(f"  {'Era':<30} {'Days':>6} {'FC-like':>10} {'Rate':>10} {'LargeRange':>12} {'V-shape':>10}")
    print(f"  {'-'*78}")

    era_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]
        n_days = len(era_data)
        n_fc = era_data['IsFlashCrashLike'].sum()
        n_large = era_data['LargeRange'].sum()
        n_vshape = era_data['VShape'].sum()

        era_results[era_name] = {
            'trading_days': int(n_days),
            'flash_crash_like': int(n_fc),
            'rate_per_year': round(float(n_fc / (n_days / 252)), 2),
            'large_range_days': int(n_large),
            'v_shape_days': int(n_vshape),
        }
        print(f"  {era_name:<30} {n_days:>6} {n_fc:>10} {n_fc/(n_days/252):>9.1f}/yr {n_large:>12} {n_vshape:>10}")

    results['era_comparison'] = era_results

    # Distribution of intraday range by era
    print(f"\n  Intraday range distribution (%):")
    print(f"  {'Era':<30} {'Median':>10} {'Mean':>10} {'P95':>10} {'P99':>10} {'Skew':>10}")
    print(f"  {'-'*80}")

    range_stats = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ranges = spy.loc[mask, 'IntradayRange'] * 100  # in percent

        range_stats[era_name] = {
            'median_pct': round(float(ranges.median()), 3),
            'mean_pct': round(float(ranges.mean()), 3),
            'p95_pct': round(float(ranges.quantile(0.95)), 3),
            'p99_pct': round(float(ranges.quantile(0.99)), 3),
            'skewness': round(float(ranges.skew()), 3),
        }
        print(f"  {era_name:<30} {ranges.median():>10.3f} {ranges.mean():>10.3f} {ranges.quantile(0.95):>10.3f} {ranges.quantile(0.99):>10.3f} {ranges.skew():>10.3f}")

    results['range_distribution'] = range_stats

    # Chi-square test: is the flash crash rate different across eras?
    observed = []
    totals = []
    for era_name in era_results:
        observed.append(era_results[era_name]['flash_crash_like'])
        totals.append(era_results[era_name]['trading_days'])

    overall_rate = sum(observed) / sum(totals)
    expected = [overall_rate * t for t in totals]

    if all(e > 0 for e in expected):
        chi2_stat = sum((o - e)**2 / e for o, e in zip(observed, expected))
        chi2_p = 1 - stats.chi2.cdf(chi2_stat, df=len(observed) - 1)
        results['chi2_test'] = {
            'statistic': round(float(chi2_stat), 4),
            'p_value': round(float(chi2_p), 4),
            'df': len(observed) - 1,
            'interpretation': 'Rates differ significantly across eras' if chi2_p < 0.05 else 'No significant difference across eras'
        }
        print(f"\n  Chi-square test for homogeneity of FC rates across eras:")
        print(f"    chi2 = {chi2_stat:.4f}, p = {chi2_p:.4f}, df = {len(observed)-1}")
        print(f"    {results['chi2_test']['interpretation']}")

    return results


# ============================================================
# Analysis 3: Volatility at Different Timescales
# ============================================================

def analyze_volatility_timescales(spy):
    """Compare daily close-to-close vol vs intraday (high-low) vol over time."""
    print("\n" + "=" * 70)
    print("[Analysis 3] Volatility at Different Timescales")
    print("=" * 70)

    results = {}

    # Parkinson volatility (intraday, based on high-low range)
    # sigma_P = sqrt(1/(4*ln(2)) * (ln(H/L))^2)
    spy['ParkVol2'] = (np.log(spy['High'] / spy['Low']))**2 / (4 * np.log(2))

    # Close-to-close volatility
    spy['CC_Vol2'] = spy['LogReturn']**2

    # Rolling ratio: Parkinson / Close-to-close
    window = 63  # quarterly
    rolling_park = spy['ParkVol2'].rolling(window).mean()
    rolling_cc = spy['CC_Vol2'].rolling(window).mean()
    vol_ratio = np.sqrt(rolling_park / rolling_cc)

    # Under no overnight information, ratio should be ~1.0
    # If overnight vol matters more (gaps), CC > Park → ratio < 1
    # If intraday noise increases (algos), Park > CC → ratio > 1

    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    print(f"\n  Parkinson-to-CloseClose vol ratio (quarterly rolling):")
    print(f"  Ratio > 1: more intraday noise relative to close-close moves")
    print(f"  Ratio < 1: overnight gaps dominate (close-close > intraday)")
    print(f"\n  {'Era':<30} {'Mean Ratio':>12} {'Std':>10} {'Ann. Park Vol':>15} {'Ann. CC Vol':>15}")
    print(f"  {'-'*82}")

    era_results = {}
    for era_name, (start, end) in eras.items():
        mask = (vol_ratio.index >= start) & (vol_ratio.index <= end)
        ratio_era = vol_ratio[mask].dropna()

        park_ann = np.sqrt(rolling_park[mask].dropna().mean() * 252) * 100
        cc_ann = np.sqrt(rolling_cc[mask].dropna().mean() * 252) * 100

        era_results[era_name] = {
            'mean_ratio': round(float(ratio_era.mean()), 4),
            'std_ratio': round(float(ratio_era.std()), 4),
            'ann_parkinson_vol_pct': round(float(park_ann), 2),
            'ann_close_close_vol_pct': round(float(cc_ann), 2),
        }
        print(f"  {era_name:<30} {ratio_era.mean():>12.4f} {ratio_era.std():>10.4f} {park_ann:>14.2f}% {cc_ann:>14.2f}%")

    results['era_comparison'] = era_results

    # Overnight vs Intraday decomposition
    print(f"\n  Overnight vs Intraday Return Decomposition:")
    print(f"  {'Era':<30} {'Overnight Var%':>15} {'Intraday Var%':>15} {'Overnight/Total':>17}")
    print(f"  {'-'*77}")

    decomp_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]

        overnight_var = era_data['GapReturn'].var()
        intraday_var = era_data['IntradayReturn'].var()
        total_var = overnight_var + intraday_var
        # note: total_var != close-to-close var due to covariance, but close enough for decomposition

        overnight_share = overnight_var / total_var

        decomp_results[era_name] = {
            'overnight_var_share': round(float(overnight_share), 4),
            'intraday_var_share': round(float(1 - overnight_share), 4),
            'overnight_ann_vol_pct': round(float(np.sqrt(overnight_var * 252) * 100), 2),
            'intraday_ann_vol_pct': round(float(np.sqrt(intraday_var * 252) * 100), 2),
        }
        print(f"  {era_name:<30} {overnight_share*100:>14.1f}% {(1-overnight_share)*100:>14.1f}% {overnight_share:>17.4f}")

    results['overnight_intraday_decomp'] = decomp_results

    # Trend test on vol ratio
    yearly_ratio = vol_ratio.resample('YE').mean().dropna()
    years_numeric = np.arange(len(yearly_ratio))
    if len(years_numeric) > 2:
        slope, intercept, r_val, p_val, std_err = stats.linregress(years_numeric, yearly_ratio.values)
        results['ratio_trend'] = {
            'slope_per_year': round(float(slope), 6),
            'r_squared': round(float(r_val**2), 4),
            'p_value': round(float(p_val), 4),
        }
        print(f"\n  Trend in vol ratio over time:")
        print(f"    Slope: {slope:.6f}/year (p={p_val:.4f})")

    return results


# ============================================================
# Analysis 4: Opening Auction Dynamics
# ============================================================

def analyze_opening_dynamics(spy):
    """How has the relative importance of the opening period changed?"""
    print("\n" + "=" * 70)
    print("[Analysis 4] Opening Auction Dynamics")
    print("=" * 70)

    results = {}

    # Using daily data: overnight gap = Open(t) / Close(t-1) - 1
    # Gap captures all overnight information processing (including algo pre-market)

    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    print(f"\n  Overnight Gap Statistics:")
    print(f"  {'Era':<30} {'Mean Gap':>12} {'Std Gap':>12} {'|Gap|>0.5%':>12} {'|Gap|>1%':>12} {'Skew':>10}")
    print(f"  {'-'*88}")

    gap_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        gaps = spy.loc[mask, 'GapReturn'] * 100  # in percent

        gap_results[era_name] = {
            'mean_gap_pct': round(float(gaps.mean()), 4),
            'std_gap_pct': round(float(gaps.std()), 4),
            'pct_above_0_5': round(float((gaps.abs() > 0.5).mean() * 100), 1),
            'pct_above_1_0': round(float((gaps.abs() > 1.0).mean() * 100), 1),
            'skewness': round(float(gaps.skew()), 4),
        }
        print(f"  {era_name:<30} {gaps.mean():>12.4f} {gaps.std():>12.4f} {(gaps.abs()>0.5).mean()*100:>11.1f}% {(gaps.abs()>1.0).mean()*100:>11.1f}% {gaps.skew():>10.4f}")

    results['overnight_gap'] = gap_results

    # Gap vs Intraday: correlation and predictive power
    print(f"\n  Gap → Intraday Return Relationship:")
    print(f"  {'Era':<30} {'Corr(Gap,Intra)':>16} {'Gap reversal%':>14} {'R² (Gap→Intra)':>16}")
    print(f"  {'-'*76}")

    gap_intra_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask].dropna(subset=['GapReturn', 'IntradayReturn'])

        corr = era_data['GapReturn'].corr(era_data['IntradayReturn'])

        # Gap reversal: gap up → intraday down, or gap down → intraday up
        gap_up = era_data['GapReturn'] > 0
        intra_down = era_data['IntradayReturn'] < 0
        reversals = ((gap_up & intra_down) | (~gap_up & ~intra_down)).mean()

        # OLS R²
        slope_gi, intercept_gi, r_gi, p_gi, _ = stats.linregress(
            era_data['GapReturn'].values, era_data['IntradayReturn'].values
        )

        gap_intra_results[era_name] = {
            'correlation': round(float(corr), 4),
            'reversal_pct': round(float(reversals * 100), 1),
            'r_squared': round(float(r_gi**2), 4),
            'beta': round(float(slope_gi), 4),
            'p_value': round(float(p_gi), 4),
        }
        print(f"  {era_name:<30} {corr:>16.4f} {reversals*100:>13.1f}% {r_gi**2:>16.4f}")

    results['gap_intraday_relationship'] = gap_intra_results

    # Information share: what fraction of daily return happens overnight?
    print(f"\n  Information Share: |overnight contribution| to daily return:")
    print(f"  {'Era':<30} {'Gap contributes':>16} {'Intra contributes':>18}")
    print(f"  {'-'*64}")

    info_share = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]

        # For cumulative return decomposition
        cum_gap = era_data['GapReturn'].sum()
        cum_intra = era_data['IntradayReturn'].sum()
        total = cum_gap + cum_intra

        if abs(total) > 1e-10:
            gap_share = cum_gap / total
            intra_share = cum_intra / total
        else:
            gap_share = intra_share = 0.5

        info_share[era_name] = {
            'gap_return_share': round(float(gap_share), 4),
            'intraday_return_share': round(float(intra_share), 4),
            'cumulative_gap_return_pct': round(float(cum_gap * 100), 2),
            'cumulative_intraday_return_pct': round(float(cum_intra * 100), 2),
        }
        print(f"  {era_name:<30} {gap_share*100:>15.1f}% {intra_share*100:>17.1f}%")

    results['information_share'] = info_share

    return results


# ============================================================
# Analysis 5: End-of-Day Dynamics
# ============================================================

def analyze_eod_dynamics(spy):
    """End-of-day patterns: MOC imbalance proxy, last-hour effects."""
    print("\n" + "=" * 70)
    print("[Analysis 5] End-of-Day Dynamics & Market-on-Close Proxy")
    print("=" * 70)

    results = {}

    # Using daily data proxies:
    # Close vs VWAP proxy: if Close > (H+L+C)/3, buying pressure at close
    spy['TypicalPrice'] = (spy['High'] + spy['Low'] + spy['Close']) / 3
    spy['CloseVsTypical'] = (spy['Close'] - spy['TypicalPrice']) / spy['TypicalPrice']

    # Close location within the day's range
    spy['CloseLocation'] = (spy['Close'] - spy['Low']) / (spy['High'] - spy['Low'] + 1e-10)
    # 0 = closed at low, 1 = closed at high, 0.5 = middle

    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    print(f"\n  Close Location Value (0=low, 0.5=middle, 1=high):")
    print(f"  {'Era':<30} {'Mean CLV':>12} {'Std':>10} {'Close>Typical%':>15} {'Close at extreme%':>18}")
    print(f"  {'-'*85}")

    clv_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]

        clv = era_data['CloseLocation']
        cvt = era_data['CloseVsTypical']

        # Close at extreme: within top/bottom 10% of range
        at_extreme = ((clv > 0.9) | (clv < 0.1)).mean()

        clv_results[era_name] = {
            'mean_clv': round(float(clv.mean()), 4),
            'std_clv': round(float(clv.std()), 4),
            'close_above_typical_pct': round(float((cvt > 0).mean() * 100), 1),
            'close_at_extreme_pct': round(float(at_extreme * 100), 1),
        }
        print(f"  {era_name:<30} {clv.mean():>12.4f} {clv.std():>10.4f} {(cvt>0).mean()*100:>14.1f}% {at_extreme*100:>17.1f}%")

    results['close_location'] = clv_results

    # Day-of-week effect evolution (a classic anomaly that algos should arbitrage away)
    print(f"\n  Day-of-Week Effect (mean daily return in bps):")
    print(f"  {'Era':<30} {'Mon':>8} {'Tue':>8} {'Wed':>8} {'Thu':>8} {'Fri':>8} {'F-stat':>10} {'p-val':>8}")
    print(f"  {'-'*88}")

    dow_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]

        dow_returns = {}
        dow_groups = []
        for dow in range(5):
            day_ret = era_data.loc[era_data.index.dayofweek == dow, 'Return']
            dow_returns[dow] = day_ret.mean() * 10000  # bps
            dow_groups.append(day_ret.values)

        # ANOVA F-test
        if all(len(g) > 5 for g in dow_groups):
            f_stat, f_p = stats.f_oneway(*dow_groups)
        else:
            f_stat, f_p = np.nan, np.nan

        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
        dow_results[era_name] = {
            day_names[i]: round(float(dow_returns[i]), 2) for i in range(5)
        }
        dow_results[era_name]['f_stat'] = round(float(f_stat), 4) if not np.isnan(f_stat) else None
        dow_results[era_name]['p_value'] = round(float(f_p), 4) if not np.isnan(f_p) else None

        print(f"  {era_name:<30} {dow_returns[0]:>8.2f} {dow_returns[1]:>8.2f} {dow_returns[2]:>8.2f} {dow_returns[3]:>8.2f} {dow_returns[4]:>8.2f} {f_stat:>10.4f} {f_p:>8.4f}")

    results['day_of_week'] = dow_results

    # Monthly seasonality persistence
    print(f"\n  Monthly Seasonality (January effect, Sell-in-May):")
    print(f"  {'Era':<30} {'Jan mean':>10} {'May-Oct':>10} {'Nov-Apr':>10} {'Diff (bps)':>12} {'t-stat':>10}")
    print(f"  {'-'*82}")

    monthly_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        era_data = spy[mask]

        jan_ret = era_data.loc[era_data.index.month == 1, 'Return']
        summer = era_data.loc[era_data.index.month.isin([5, 6, 7, 8, 9, 10]), 'Return']
        winter = era_data.loc[era_data.index.month.isin([11, 12, 1, 2, 3, 4]), 'Return']

        if len(summer) > 10 and len(winter) > 10:
            t_stat_mth, p_val_mth = stats.ttest_ind(winter.values, summer.values)
        else:
            t_stat_mth, p_val_mth = np.nan, np.nan

        monthly_results[era_name] = {
            'jan_mean_bps': round(float(jan_ret.mean() * 10000), 2),
            'summer_mean_bps': round(float(summer.mean() * 10000), 2),
            'winter_mean_bps': round(float(winter.mean() * 10000), 2),
            'winter_minus_summer_bps': round(float((winter.mean() - summer.mean()) * 10000), 2),
            't_stat': round(float(t_stat_mth), 4) if not np.isnan(t_stat_mth) else None,
        }
        print(f"  {era_name:<30} {jan_ret.mean()*10000:>10.2f} {summer.mean()*10000:>10.2f} {winter.mean()*10000:>10.2f} {(winter.mean()-summer.mean())*10000:>12.2f} {t_stat_mth:>10.4f}")

    results['monthly_seasonality'] = monthly_results

    return results


# ============================================================
# Analysis 6: Additional Microstructure Measures
# ============================================================

def analyze_microstructure_extras(spy):
    """Additional measures: autocorrelation decay, return distribution changes."""
    print("\n" + "=" * 70)
    print("[Analysis 6] Return Distribution Evolution & Tail Behavior")
    print("=" * 70)

    results = {}

    eras = {
        '2001-2005 (Pre-algo)': ('2001-01-01', '2005-12-31'),
        '2006-2010 (Early algo)': ('2006-01-01', '2010-12-31'),
        '2011-2015 (HFT peak)': ('2011-01-01', '2015-12-31'),
        '2016-2020 (ML era)': ('2016-01-01', '2020-12-31'),
        '2021-2024 (AI era)': ('2021-01-01', '2024-12-31'),
    }

    # Return distribution moments
    print(f"\n  Return Distribution Moments:")
    print(f"  {'Era':<30} {'Mean(bps)':>10} {'Std(%)':>10} {'Skew':>10} {'Kurt':>10} {'JB stat':>12} {'JB p':>10}")
    print(f"  {'-'*92}")

    dist_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ret = spy.loc[mask, 'Return'].dropna()

        mean_bps = ret.mean() * 10000
        std_pct = ret.std() * 100
        skew = ret.skew()
        kurt = ret.kurtosis()

        # Jarque-Bera test
        n = len(ret)
        jb_stat = (n / 6) * (skew**2 + (kurt**2) / 4)
        jb_p = 1 - stats.chi2.cdf(jb_stat, df=2)

        dist_results[era_name] = {
            'mean_bps': round(float(mean_bps), 2),
            'std_pct': round(float(std_pct), 3),
            'skewness': round(float(skew), 4),
            'kurtosis': round(float(kurt), 4),
            'jarque_bera': round(float(jb_stat), 2),
            'jb_p_value': round(float(jb_p), 6),
        }
        print(f"  {era_name:<30} {mean_bps:>10.2f} {std_pct:>10.3f} {skew:>10.4f} {kurt:>10.4f} {jb_stat:>12.2f} {jb_p:>10.6f}")

    results['distribution'] = dist_results

    # Tail event frequency (>2σ, >3σ)
    print(f"\n  Tail Event Frequency:")
    print(f"  {'Era':<30} {'>2σ actual':>12} {'>2σ normal':>12} {'Ratio':>8} {'>3σ actual':>12} {'>3σ normal':>12} {'Ratio':>8}")
    print(f"  {'-'*94}")

    tail_results = {}
    normal_2sigma = 2 * stats.norm.sf(2) * 100  # ~4.55%
    normal_3sigma = 2 * stats.norm.sf(3) * 100  # ~0.27%

    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ret = spy.loc[mask, 'Return'].dropna()
        sigma = ret.std()

        beyond_2 = (ret.abs() > 2 * sigma).mean() * 100
        beyond_3 = (ret.abs() > 3 * sigma).mean() * 100

        tail_results[era_name] = {
            'beyond_2sigma_pct': round(float(beyond_2), 2),
            'beyond_3sigma_pct': round(float(beyond_3), 2),
            'ratio_2sigma': round(float(beyond_2 / normal_2sigma), 2),
            'ratio_3sigma': round(float(beyond_3 / normal_3sigma), 2),
        }
        print(f"  {era_name:<30} {beyond_2:>11.2f}% {normal_2sigma:>11.2f}% {beyond_2/normal_2sigma:>8.2f} {beyond_3:>11.2f}% {normal_3sigma:>11.2f}% {beyond_3/normal_3sigma:>8.2f}")

    results['tail_events'] = tail_results

    # Autocorrelation structure: ACF at multiple lags
    print(f"\n  Autocorrelation Structure (returns):")
    print(f"  {'Era':<30} {'ACF(1)':>10} {'ACF(2)':>10} {'ACF(5)':>10} {'ACF(10)':>10} {'ACF(20)':>10}")
    print(f"  {'-'*80}")

    acf_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ret = spy.loc[mask, 'Return'].dropna()

        acf_vals = {}
        for lag in [1, 2, 5, 10, 20]:
            acf_vals[f'lag_{lag}'] = round(float(ret.autocorr(lag=lag)), 4)

        acf_results[era_name] = acf_vals
        print(f"  {era_name:<30} {acf_vals['lag_1']:>10.4f} {acf_vals['lag_2']:>10.4f} {acf_vals['lag_5']:>10.4f} {acf_vals['lag_10']:>10.4f} {acf_vals['lag_20']:>10.4f}")

    # Autocorrelation structure: ACF of absolute returns
    print(f"\n  Autocorrelation Structure (|returns|):")
    print(f"  {'Era':<30} {'ACF(1)':>10} {'ACF(2)':>10} {'ACF(5)':>10} {'ACF(10)':>10} {'ACF(20)':>10}")
    print(f"  {'-'*80}")

    acf_abs_results = {}
    for era_name, (start, end) in eras.items():
        mask = (spy.index >= start) & (spy.index <= end)
        ret = spy.loc[mask, 'Return'].abs().dropna()

        acf_vals = {}
        for lag in [1, 2, 5, 10, 20]:
            acf_vals[f'lag_{lag}'] = round(float(ret.autocorr(lag=lag)), 4)

        acf_abs_results[era_name] = acf_vals
        print(f"  {era_name:<30} {acf_vals['lag_1']:>10.4f} {acf_vals['lag_2']:>10.4f} {acf_vals['lag_5']:>10.4f} {acf_vals['lag_10']:>10.4f} {acf_vals['lag_20']:>10.4f}")

    results['acf_returns'] = acf_results
    results['acf_abs_returns'] = acf_abs_results

    return results


# ============================================================
# Synthesis
# ============================================================

def synthesize_findings(all_results):
    """Combine all findings into a coherent narrative."""
    print("\n" + "=" * 70)
    print("SYNTHESIS: How Has Algorithmic Trading Changed Market Dynamics?")
    print("=" * 70)

    findings = []

    # 1. Efficiency
    eff = all_results.get('efficiency', {})
    trend = eff.get('trend', {})
    if trend.get('p_value', 1) < 0.10:
        findings.append(f"1. MARKET EFFICIENCY: ACF(1) trend is {trend['interpretation']} "
                       f"(slope={trend['slope_per_year']:.6f}/yr, p={trend['p_value']:.4f}). "
                       f"Markets {'have' if trend['interpretation']=='declining' else 'have not'} become more efficient.")
    else:
        findings.append(f"1. MARKET EFFICIENCY: No significant trend in ACF(1) over 25 years "
                       f"(slope={trend.get('slope_per_year', 'N/A')}, p={trend.get('p_value', 'N/A')}). "
                       f"Market efficiency hasn't clearly changed at the daily frequency.")

    # 2. Flash crashes
    fc = all_results.get('flash_crashes', {})
    chi2 = fc.get('chi2_test', {})
    findings.append(f"2. FLASH CRASHES: {chi2.get('interpretation', 'N/A')} "
                   f"(chi2={chi2.get('statistic', 'N/A')}, p={chi2.get('p_value', 'N/A')}).")

    # 3. Vol timescales
    vol = all_results.get('volatility_timescales', {})
    ratio_trend = vol.get('ratio_trend', {})
    if ratio_trend:
        findings.append(f"3. VOLATILITY TIMESCALES: Parkinson/CC ratio trend slope={ratio_trend.get('slope_per_year', 'N/A')}/yr "
                       f"(p={ratio_trend.get('p_value', 'N/A')}). "
                       f"{'Increasing intraday noise' if ratio_trend.get('slope_per_year', 0) > 0 else 'Stable intraday-to-daily vol relationship'}.")

    # 4. Opening dynamics
    opening = all_results.get('opening_dynamics', {})
    info = opening.get('information_share', {})
    early_gap = list(info.values())[0] if info else {}
    late_gap = list(info.values())[-1] if info else {}
    findings.append(f"4. OPENING DYNAMICS: Overnight gap's share of returns was "
                   f"{early_gap.get('gap_return_share', 'N/A')*100:.1f}% in early era "
                   f"→ {late_gap.get('gap_return_share', 'N/A')*100:.1f}% in latest era.")

    # 5. EOD dynamics
    eod = all_results.get('eod_dynamics', {})
    dow = eod.get('day_of_week', {})
    early_dow = list(dow.values())[0] if dow else {}
    late_dow = list(dow.values())[-1] if dow else {}
    findings.append(f"5. DAY-OF-WEEK EFFECT: {early_dow.get('p_value', 'N/A')} (early era) → "
                   f"{late_dow.get('p_value', 'N/A')} (latest era). "
                   f"{'Calendar anomaly has been arbitraged away' if (late_dow.get('p_value', 0) or 1) > 0.1 else 'Calendar anomaly persists'}.")

    # 6. Distribution
    micro = all_results.get('microstructure', {})
    dist = micro.get('distribution', {})
    early_kurt = list(dist.values())[0] if dist else {}
    late_kurt = list(dist.values())[-1] if dist else {}
    findings.append(f"6. TAIL BEHAVIOR: Kurtosis was {early_kurt.get('kurtosis', 'N/A')} (early) → "
                   f"{late_kurt.get('kurtosis', 'N/A')} (latest). "
                   f"{'Fatter tails' if (late_kurt.get('kurtosis', 0) or 0) > (early_kurt.get('kurtosis', 0) or 0) else 'Thinner tails'} in the algo era.")

    print()
    for f in findings:
        print(f"  {f}")

    return findings


# ============================================================
# Main
# ============================================================

def main():
    spy = download_daily_data()

    all_results = {}

    # Run all analyses
    all_results['efficiency'] = analyze_market_efficiency(spy)
    all_results['flash_crashes'] = analyze_flash_crashes(spy)
    all_results['volatility_timescales'] = analyze_volatility_timescales(spy)
    all_results['opening_dynamics'] = analyze_opening_dynamics(spy)
    all_results['eod_dynamics'] = analyze_eod_dynamics(spy)
    all_results['microstructure'] = analyze_microstructure_extras(spy)

    # Synthesize
    findings = synthesize_findings(all_results)
    all_results['synthesis'] = findings

    # Metadata
    all_results['metadata'] = {
        'experiment_id': 'K410',
        'title': 'Has Algorithmic Trading Changed Market Dynamics?',
        'asset': 'SPY',
        'period': '2000-01-01 to 2024-12-31',
        'data_source': 'yfinance',
        'sample_size': len(spy),
        'run_date': datetime.now().isoformat(),
        'methodology': 'Market microstructure analysis across 5 eras (2001-2024)',
        'eras': ['2001-2005 (Pre-algo)', '2006-2010 (Early algo)',
                 '2011-2015 (HFT peak)', '2016-2020 (ML era)', '2021-2024 (AI era)'],
        'limitations': [
            'Daily data only — cannot directly measure intraday algo behavior',
            'SPY only — results may differ for individual stocks or other ETFs',
            'Era boundaries are approximate — algo adoption was gradual',
            'Confounding factors: regulation changes (Reg NMS 2007), market events (2008 crisis, COVID)',
            'Overnight gap is a proxy — cannot decompose pre-market vs actual opening auction',
            'No causal identification — correlation between time trend and algo adoption',
        ],
    }

    # Save results
    output_path = 'experiments/k410_algo_impact_results.json'

    # Convert any non-serializable types
    def convert(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return obj

    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2, default=convert)

    print(f"\n  Results saved to: {output_path}")
    print(f"\n{'='*70}")
    print(f"K410 COMPLETE — {len(spy)} trading days analyzed across 5 eras")
    print(f"{'='*70}")

    return all_results


if __name__ == '__main__':
    results = main()
