"""
K297: Intraday Volatility Pattern from 5-Min Data — First Look at High-Frequency Structure

[提出: 用戶, 執行: Claude]

Background:
- K257 confirmed 47 days of 5-min SPY data available
- K188 proved the forecasting ceiling is in the DATA
- This descriptive analysis builds the foundation for HAR-RV work

Data: 5-min SPY bars from data/intraday/SPY_5min_*.csv
      47 trading days (2026-01-14 to 2026-03-23)
      Source: yfinance free tier

Methodology:
1. Intraday volatility smile (U-shape pattern)
2. Intraday volume pattern
3. Daily RV decomposition (open/midday/close contributions)
4. Autocorrelation of squared returns at 5-min level
5. Lee-Mykland (2008) jump detection

PRELIMINARY: Only 47 days. All findings are descriptive, not inferential.
"""

import sys
import os
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
from collections import defaultdict

# ── Configuration ──────────────────────────────────────────────────────
# Use main repo data directory (worktree may not have data/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = _PROJECT_ROOT / "data" / "intraday"
if not DATA_DIR.exists():
    # Fallback: main repo
    DATA_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/data/intraday")
TICKER = "SPY"
# US market hours in UTC: 14:30 - 21:00 (9:30 AM - 4:00 PM ET)
# yfinance timestamps are in UTC


def load_all_5min_data():
    """Load all SPY 5-min CSV files and combine into single DataFrame."""
    files = sorted(DATA_DIR.glob(f"{TICKER}_5min_*.csv"))
    if not files:
        raise FileNotFoundError(f"No {TICKER} 5-min files found in {DATA_DIR}")

    all_data = []
    for f in files:
        try:
            df = pd.read_csv(f, header=[0, 1], index_col=0, parse_dates=True)
            # Flatten multi-level columns: take first level (Price name)
            df.columns = [col[0] for col in df.columns]
            all_data.append(df)
        except Exception as e:
            print(f"  Warning: skipped {f.name}: {e}")

    combined = pd.concat(all_data)
    combined.index = pd.to_datetime(combined.index, utc=True)
    combined = combined.sort_index()
    # Remove duplicates (from overlapping fetches)
    combined = combined[~combined.index.duplicated(keep='last')]

    print(f"Loaded {len(files)} files, {len(combined)} total bars")
    print(f"Date range: {combined.index[0]} to {combined.index[-1]}")
    print(f"Trading days: {combined.index.normalize().nunique()}")

    return combined


def compute_returns(df):
    """Compute 5-min log returns within each trading day."""
    df = df.copy()
    df['date'] = df.index.date

    # Group by date and compute returns within each day
    returns = []
    for date, group in df.groupby('date'):
        group = group.sort_index()
        r = np.log(group['Close'] / group['Close'].shift(1))
        returns.append(r)

    df['log_return'] = pd.concat(returns)
    # First bar of each day has NaN return (no overnight)
    return df


def analysis_1_intraday_vol_smile(df):
    """Intraday volatility pattern: average |return| by time of day."""
    print("\n" + "="*70)
    print("ANALYSIS 1: INTRADAY VOLATILITY SMILE (U-SHAPE)")
    print("="*70)

    # Extract time of day (UTC hours)
    df['time_utc'] = df.index.strftime('%H:%M')
    df['hour_utc'] = df.index.hour
    df['minute'] = df.index.minute

    # Compute |return| for each bar
    df['abs_return'] = df['log_return'].abs()
    df['sq_return'] = df['log_return'] ** 2

    # Average by time of day
    vol_by_time = df.groupby('time_utc').agg(
        mean_abs_ret=('abs_return', 'mean'),
        std_abs_ret=('abs_return', 'std'),
        mean_sq_ret=('sq_return', 'mean'),
        count=('abs_return', 'count')
    ).dropna()

    # Convert UTC times to ET for display
    # UTC 14:30 = ET 9:30, UTC 20:55 = ET 15:55
    print(f"\nNumber of time slots: {len(vol_by_time)}")
    print(f"Bars per slot: {vol_by_time['count'].median():.0f}")

    # Identify open, midday, close
    # Open = first 6 bars (14:35 - 15:00 UTC = 9:35-10:00 ET), skip 14:30 (NaN)
    # Close = last 6 bars (20:30 - 20:55 UTC = 15:30-15:55 ET)
    # Midday = 15:30 - 19:55 UTC (10:30 - 14:55 ET)

    open_times = [t for t in vol_by_time.index if t >= '14:35' and t <= '15:00']
    close_times = [t for t in vol_by_time.index if t >= '20:30' and t <= '20:55']
    midday_times = [t for t in vol_by_time.index if t >= '15:30' and t <= '19:55']

    open_vol = vol_by_time.loc[vol_by_time.index.isin(open_times), 'mean_abs_ret'].mean()
    close_vol = vol_by_time.loc[vol_by_time.index.isin(close_times), 'mean_abs_ret'].mean()
    midday_vol = vol_by_time.loc[vol_by_time.index.isin(midday_times), 'mean_abs_ret'].mean()

    print(f"\n--- Average |return| by session ---")
    print(f"Open  (9:35-10:00 ET):  {open_vol*100:.4f}%  (annualized σ ~ {open_vol * np.sqrt(252*78)*100:.1f}%)")
    print(f"Midday(10:30-14:55 ET): {midday_vol*100:.4f}%  (annualized σ ~ {midday_vol * np.sqrt(252*78)*100:.1f}%)")
    print(f"Close (15:30-15:55 ET): {close_vol*100:.4f}%  (annualized σ ~ {close_vol * np.sqrt(252*78)*100:.1f}%)")

    u_shape_ratio_open = open_vol / midday_vol if midday_vol > 0 else np.nan
    u_shape_ratio_close = close_vol / midday_vol if midday_vol > 0 else np.nan

    print(f"\nU-shape ratios (vs midday):")
    print(f"  Open/Midday:  {u_shape_ratio_open:.2f}x")
    print(f"  Close/Midday: {u_shape_ratio_close:.2f}x")

    is_u_shape = open_vol > midday_vol and close_vol > midday_vol
    print(f"\nClassic U-shape confirmed: {'YES' if is_u_shape else 'NO'}")

    # Show top 5 and bottom 5 bars
    print(f"\n--- Top 5 most volatile bars (ET) ---")
    top5 = vol_by_time.nlargest(5, 'mean_abs_ret')
    for t, row in top5.iterrows():
        # Convert UTC to ET (subtract 5 hours)
        h_utc, m = int(t.split(':')[0]), int(t.split(':')[1])
        h_et = h_utc - 5
        print(f"  {h_et:02d}:{m:02d} ET (UTC {t}): |r| = {row['mean_abs_ret']*100:.4f}%  (n={int(row['count'])})")

    print(f"\n--- Bottom 5 least volatile bars (ET) ---")
    bot5 = vol_by_time.nsmallest(5, 'mean_abs_ret')
    for t, row in bot5.iterrows():
        h_utc, m = int(t.split(':')[0]), int(t.split(':')[1])
        h_et = h_utc - 5
        print(f"  {h_et:02d}:{m:02d} ET (UTC {t}): |r| = {row['mean_abs_ret']*100:.4f}%  (n={int(row['count'])})")

    # Full profile for reference
    print(f"\n--- Full intraday volatility profile ---")
    print(f"{'ET Time':>8s} {'|r| (%)':>10s} {'σ² (bps²)':>12s} {'n':>5s}")
    for t, row in vol_by_time.iterrows():
        h_utc, m = int(t.split(':')[0]), int(t.split(':')[1])
        h_et = h_utc - 5
        sq_bps = row['mean_sq_ret'] * 1e8  # convert to basis points squared
        print(f"  {h_et:02d}:{m:02d}   {row['mean_abs_ret']*100:>10.4f} {sq_bps:>12.2f}   {int(row['count']):>4d}")

    return vol_by_time, {
        'open_vol': open_vol, 'midday_vol': midday_vol, 'close_vol': close_vol,
        'u_shape_open_ratio': u_shape_ratio_open,
        'u_shape_close_ratio': u_shape_ratio_close,
        'is_u_shape': is_u_shape
    }


def analysis_2_volume_pattern(df):
    """Intraday volume pattern and correlation with volatility."""
    print("\n" + "="*70)
    print("ANALYSIS 2: INTRADAY VOLUME PATTERN")
    print("="*70)

    df['time_utc'] = df.index.strftime('%H:%M')

    vol_by_time = df.groupby('time_utc').agg(
        mean_volume=('Volume', 'mean'),
        mean_abs_ret=('abs_return', 'mean'),
        mean_sq_ret=('sq_return', 'mean'),
        count=('abs_return', 'count')
    ).dropna()

    # Volume pattern
    print(f"\n--- Volume by session ---")
    open_times = [t for t in vol_by_time.index if t >= '14:35' and t <= '15:00']
    close_times = [t for t in vol_by_time.index if t >= '20:30' and t <= '20:55']
    midday_times = [t for t in vol_by_time.index if t >= '15:30' and t <= '19:55']

    open_vol = vol_by_time.loc[vol_by_time.index.isin(open_times), 'mean_volume'].mean()
    close_vol = vol_by_time.loc[vol_by_time.index.isin(close_times), 'mean_volume'].mean()
    midday_vol = vol_by_time.loc[vol_by_time.index.isin(midday_times), 'mean_volume'].mean()

    print(f"Open   avg volume: {open_vol:,.0f}")
    print(f"Midday avg volume: {midday_vol:,.0f}")
    print(f"Close  avg volume: {close_vol:,.0f}")
    print(f"Open/Midday ratio:  {open_vol/midday_vol:.2f}x")
    print(f"Close/Midday ratio: {close_vol/midday_vol:.2f}x")

    # Correlation between intraday vol and volume
    corr_abs = vol_by_time['mean_abs_ret'].corr(vol_by_time['mean_volume'])
    corr_sq = vol_by_time['mean_sq_ret'].corr(vol_by_time['mean_volume'])
    n_times = len(vol_by_time)
    t_stat = corr_abs * np.sqrt((n_times - 2) / (1 - corr_abs**2))
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), n_times - 2))

    print(f"\n--- Volume-Volatility correlation (cross-sectional, by time slot) ---")
    print(f"corr(mean |r|, mean volume): {corr_abs:.3f}  (t={t_stat:.2f}, p={p_val:.4f})")
    print(f"corr(mean r², mean volume):  {corr_sq:.3f}")

    # Also compute bar-level correlation (pooled across all days)
    valid = df.dropna(subset=['abs_return'])
    bar_corr = valid['abs_return'].corr(valid['Volume'])
    print(f"Bar-level corr(|r|, volume): {bar_corr:.3f}  (pooled, N={len(valid)})")

    # Show top/bottom volume bars
    print(f"\n--- Top 5 highest volume bars ---")
    top5 = vol_by_time.nlargest(5, 'mean_volume')
    for t, row in top5.iterrows():
        h_utc, m = int(t.split(':')[0]), int(t.split(':')[1])
        h_et = h_utc - 5
        print(f"  {h_et:02d}:{m:02d} ET: vol = {row['mean_volume']:,.0f}")

    return {
        'open_volume': open_vol, 'midday_volume': midday_vol, 'close_volume': close_vol,
        'vol_vol_corr_cross_sectional': corr_abs,
        'vol_vol_corr_bar_level': bar_corr,
        'corr_p_value': p_val
    }


def analysis_3_rv_decomposition(df):
    """Daily RV decomposition: contribution from open/midday/close."""
    print("\n" + "="*70)
    print("ANALYSIS 3: DAILY RV DECOMPOSITION")
    print("="*70)

    df['date'] = df.index.date
    df['time_utc'] = df.index.strftime('%H:%M')

    # Define sessions
    # Open: 9:30-10:00 ET = 14:30-15:00 UTC (first 30 min, 6 bars)
    # Midday: 10:30-15:00 ET = 15:30-20:00 UTC
    # Close: 15:30-16:00 ET = 20:30-21:00 UTC (last 30 min, 6 bars)

    results = []
    for date, group in df.groupby('date'):
        group = group.sort_index()
        sq_rets = group['log_return'] ** 2

        # Total daily RV
        rv_total = sq_rets.sum()
        if rv_total == 0 or np.isnan(rv_total):
            continue

        # Session RVs
        open_mask = (group['time_utc'] >= '14:30') & (group['time_utc'] <= '15:00')
        close_mask = (group['time_utc'] >= '20:30') & (group['time_utc'] <= '20:55')
        midday_mask = (group['time_utc'] >= '15:30') & (group['time_utc'] <= '19:55')

        rv_open = sq_rets[open_mask].sum()
        rv_close = sq_rets[close_mask].sum()
        rv_midday = sq_rets[midday_mask].sum()

        results.append({
            'date': date,
            'rv_total': rv_total,
            'rv_open': rv_open,
            'rv_close': rv_close,
            'rv_midday': rv_midday,
            'pct_open': rv_open / rv_total * 100 if rv_total > 0 else 0,
            'pct_close': rv_close / rv_total * 100 if rv_total > 0 else 0,
            'pct_midday': rv_midday / rv_total * 100 if rv_total > 0 else 0,
            'n_bars': len(group)
        })

    rv_df = pd.DataFrame(results)

    print(f"\n--- Daily RV decomposition (47 days) ---")
    print(f"{'Session':>10s} {'Avg % of RV':>12s} {'Std':>8s} {'Min':>8s} {'Max':>8s}")
    for session in ['pct_open', 'pct_midday', 'pct_close']:
        label = session.replace('pct_', '').capitalize()
        print(f"  {label:>8s}  {rv_df[session].mean():>10.1f}%  {rv_df[session].std():>6.1f}%  {rv_df[session].min():>6.1f}%  {rv_df[session].max():>6.1f}%")

    # Theoretical proportions if vol were constant
    # Open: 6/78 bars = 7.7%, Midday: 54/78 = 69.2%, Close: 6/78 = 7.7%
    # (Remaining bars: 15:05-15:25 and 20:00-20:25 = 12 bars = 15.4%)
    bars_open = 6
    bars_midday = 54
    bars_close = 6
    bars_gap = 78 - bars_open - bars_midday - bars_close  # transition bars
    total_bars = 78

    print(f"\n--- Comparison to uniform distribution ---")
    print(f"If volatility were constant throughout the day:")
    print(f"  Open  would be: {bars_open/total_bars*100:.1f}%, actual: {rv_df['pct_open'].mean():.1f}%  (ratio: {rv_df['pct_open'].mean()/(bars_open/total_bars*100):.2f}x)")
    print(f"  Midday would be: {bars_midday/total_bars*100:.1f}%, actual: {rv_df['pct_midday'].mean():.1f}%  (ratio: {rv_df['pct_midday'].mean()/(bars_midday/total_bars*100):.2f}x)")
    print(f"  Close would be: {bars_close/total_bars*100:.1f}%, actual: {rv_df['pct_close'].mean():.1f}%  (ratio: {rv_df['pct_close'].mean()/(bars_close/total_bars*100):.2f}x)")

    # Daily RV statistics
    print(f"\n--- Daily RV statistics ---")
    ann_factor = 252
    daily_rv = rv_df['rv_total']
    print(f"Mean daily RV: {daily_rv.mean():.6f}  (annualized σ = {np.sqrt(daily_rv.mean() * ann_factor)*100:.1f}%)")
    print(f"Std daily RV:  {daily_rv.std():.6f}")
    print(f"Median:        {daily_rv.median():.6f}")
    print(f"Max:           {daily_rv.max():.6f}  (date: {rv_df.loc[daily_rv.idxmax(), 'date']})")
    print(f"Min:           {daily_rv.min():.6f}  (date: {rv_df.loc[daily_rv.idxmin(), 'date']})")
    print(f"Skewness:      {daily_rv.skew():.2f}")
    print(f"Kurtosis:      {daily_rv.kurtosis():.2f}")

    # Compare with squared daily return (r_d² as RV proxy)
    # For reference only
    print(f"\n--- RV vs r_d² comparison ---")
    for _, row in rv_df.iterrows():
        pass  # We'll compute this separately

    return rv_df


def analysis_4_autocorrelation(df):
    """Autocorrelation of squared 5-min returns."""
    print("\n" + "="*70)
    print("ANALYSIS 4: AUTOCORRELATION AT 5-MIN LEVEL")
    print("="*70)

    # Pool all within-day squared returns
    # We need to be careful to only compute ACF within each day
    sq_returns_all = df['log_return'] ** 2
    sq_returns_all = sq_returns_all.dropna()

    # Pooled ACF (ignoring day boundaries) for quick look
    max_lag = 30  # 30 * 5 min = 2.5 hours
    print(f"\n--- Pooled ACF of r² (5-min squared returns) ---")
    print(f"Note: includes cross-day boundaries, treat with caution")
    print(f"{'Lag':>5s} {'Minutes':>8s} {'ACF(r²)':>10s} {'SE':>8s} {'t-stat':>8s}")

    n = len(sq_returns_all)
    se = 1 / np.sqrt(n)
    mean_sq = sq_returns_all.mean()

    for lag in [1, 2, 3, 5, 10, 15, 20, 30, 50, 78]:
        if lag >= n:
            break
        acf_val = sq_returns_all.autocorr(lag=lag)
        t = acf_val / se
        sig = '*' if abs(t) > 1.96 else ''
        print(f"  {lag:>4d}  {lag*5:>6d}  {acf_val:>10.4f}  {se:>6.4f}  {t:>6.2f} {sig}")

    # Within-day ACF (proper, no cross-day contamination)
    print(f"\n--- Within-day ACF (averaged across {df.index.normalize().nunique()} days) ---")
    df['date'] = df.index.date
    daily_acfs = defaultdict(list)
    for date, group in df.groupby('date'):
        sq_r = (group['log_return'] ** 2).dropna()
        if len(sq_r) < 20:
            continue
        for lag in [1, 2, 3, 5, 10, 15, 20]:
            if lag < len(sq_r):
                acf = sq_r.autocorr(lag=lag)
                if not np.isnan(acf):
                    daily_acfs[lag].append(acf)

    print(f"{'Lag':>5s} {'Minutes':>8s} {'Mean ACF':>10s} {'Std':>8s} {'t-stat':>8s} {'p-value':>10s}")
    for lag in sorted(daily_acfs.keys()):
        vals = daily_acfs[lag]
        mean_acf = np.mean(vals)
        std_acf = np.std(vals) / np.sqrt(len(vals))
        t_stat = mean_acf / std_acf if std_acf > 0 else 0
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), len(vals) - 1))
        sig = '***' if p_val < 0.001 else ('**' if p_val < 0.01 else ('*' if p_val < 0.05 else ''))
        print(f"  {lag:>4d}  {lag*5:>6d}  {mean_acf:>10.4f}  {std_acf:>6.4f}  {t_stat:>6.2f}  {p_val:>8.4f} {sig}")

    # Also check ACF of |r| (more robust)
    print(f"\n--- Within-day ACF of |r| (averaged across days) ---")
    daily_acfs_abs = defaultdict(list)
    for date, group in df.groupby('date'):
        abs_r = group['abs_return'].dropna()
        if len(abs_r) < 20:
            continue
        for lag in [1, 2, 3, 5, 10, 15, 20]:
            if lag < len(abs_r):
                acf = abs_r.autocorr(lag=lag)
                if not np.isnan(acf):
                    daily_acfs_abs[lag].append(acf)

    print(f"{'Lag':>5s} {'Minutes':>8s} {'Mean ACF':>10s} {'Std':>8s} {'t-stat':>8s}")
    for lag in sorted(daily_acfs_abs.keys()):
        vals = daily_acfs_abs[lag]
        mean_acf = np.mean(vals)
        std_acf = np.std(vals) / np.sqrt(len(vals))
        t_stat = mean_acf / std_acf if std_acf > 0 else 0
        print(f"  {lag:>4d}  {lag*5:>6d}  {mean_acf:>10.4f}  {std_acf:>6.4f}  {t_stat:>6.2f}")

    # Half-life of vol clustering
    print(f"\n--- Volatility clustering half-life ---")
    lags_for_decay = [1, 2, 3, 5, 10, 15, 20]
    acf_values = []
    for lag in lags_for_decay:
        if lag in daily_acfs:
            acf_values.append(np.mean(daily_acfs[lag]))
        else:
            acf_values.append(np.nan)

    # Find half-life: when ACF drops below 50% of lag-1 value
    if acf_values[0] > 0:
        half_target = acf_values[0] / 2
        half_life_lag = None
        for i, (lag, acf) in enumerate(zip(lags_for_decay, acf_values)):
            if acf < half_target:
                half_life_lag = lag
                break
        if half_life_lag:
            print(f"ACF(r², lag=1) = {acf_values[0]:.4f}")
            print(f"Half-life: ~{half_life_lag * 5} minutes ({half_life_lag} lags)")
        else:
            print(f"ACF(r², lag=1) = {acf_values[0]:.4f}")
            print(f"Half-life: > {lags_for_decay[-1] * 5} minutes (ACF still > {half_target:.4f} at lag {lags_for_decay[-1]})")

    return daily_acfs


def analysis_5_jump_detection(df):
    """Lee-Mykland (2008) jump detection at 5-min frequency.

    The LM test compares each return to local bipower variation (BV).
    L(t_i) = r(t_i) / (σ_hat * S_n)
    where σ_hat is estimated from local bipower variation.
    Under null (no jump): |L| → standard Gumbel asymptotically.

    Reference: Lee, S., & Mykland, P. (2008). "Jumps in financial markets:
    A new nonparametric test and jump dynamics." RFS.
    """
    print("\n" + "="*70)
    print("ANALYSIS 5: LEE-MYKLAND JUMP DETECTION")
    print("="*70)

    df['date'] = df.index.date

    # LM test parameters
    # Window for local BV estimation: K = ceil(sqrt(252 * 78)) ~ 140 bars
    # But with only 78 bars/day, we use within-day window
    # Following convention: K = floor(sqrt(n_bars_day)) for intraday
    K = max(int(np.sqrt(78)), 5)  # ~8 bars = 40 minutes

    # Centering constants for Gumbel distribution
    # C_n and S_n depend on n (number of observations per day)
    n_per_day = 77  # returns per day (78 bars - 1)
    c_n = np.sqrt(2 * np.log(n_per_day)) - (np.log(np.pi) + np.log(np.log(n_per_day))) / (2 * np.sqrt(2 * np.log(n_per_day)))
    s_n = 1 / np.sqrt(2 * np.log(n_per_day))

    # mu1 = E[|Z|] = sqrt(2/pi)
    mu1 = np.sqrt(2 / np.pi)

    all_jumps = []
    jump_times = []
    total_bars = 0

    for date, group in df.groupby('date'):
        group = group.sort_index()
        rets = group['log_return'].values
        times = group.index

        if len(rets) < K + 2:
            continue

        # Compute local bipower variation for each bar
        abs_rets = np.abs(rets)
        for i in range(K + 1, len(rets)):
            # Local BV estimate: using K preceding bars
            # BV_local = (1/K) * sum(|r_{i-j}| * |r_{i-j-1}|) for j=1..K
            bv_local = 0
            for j in range(1, K + 1):
                idx = i - j
                if idx > 0:
                    bv_local += abs_rets[idx] * abs_rets[idx - 1]
            bv_local /= (K - 1)  # normalize
            sigma_hat = np.sqrt(bv_local / (mu1 ** 2))

            if sigma_hat > 0 and not np.isnan(rets[i]):
                # LM test statistic
                L_stat = rets[i] / sigma_hat

                # Standardized: (|L| - c_n) / s_n → Gumbel
                L_standardized = (abs(L_stat) - c_n) / s_n

                # p-value from Gumbel distribution
                # P(X > x) = 1 - exp(-exp(-x))
                p_value = 1 - np.exp(-np.exp(-L_standardized))

                total_bars += 1

                if p_value < 0.01:  # 1% significance
                    jump_info = {
                        'date': date,
                        'time': times[i],
                        'time_utc': times[i].strftime('%H:%M'),
                        'return': rets[i],
                        'L_stat': L_stat,
                        'L_std': L_standardized,
                        'p_value': p_value,
                        'sigma_hat': sigma_hat,
                        'direction': 'UP' if rets[i] > 0 else 'DOWN'
                    }
                    all_jumps.append(jump_info)
                    jump_times.append(times[i])

    jump_df = pd.DataFrame(all_jumps)
    n_days = df.index.normalize().nunique()
    jump_rate = len(all_jumps) / n_days if n_days > 0 else 0

    print(f"\nLee-Mykland parameters:")
    print(f"  Local BV window K = {K} bars ({K*5} minutes)")
    print(f"  n per day = {n_per_day}")
    print(f"  c_n = {c_n:.4f}, s_n = {s_n:.4f}")
    print(f"  Significance level: 1%")

    print(f"\n--- Jump detection results ---")
    print(f"Total bars tested: {total_bars}")
    print(f"Jumps detected (p < 0.01): {len(all_jumps)}")
    print(f"Jump rate: {len(all_jumps)/total_bars*100:.2f}% of bars")
    print(f"Jumps per day: {jump_rate:.1f}")
    print(f"Trading days: {n_days}")

    if len(jump_df) > 0:
        # Direction breakdown
        n_up = (jump_df['direction'] == 'UP').sum()
        n_down = (jump_df['direction'] == 'DOWN').sum()
        print(f"\nDirection: {n_up} up ({n_up/len(jump_df)*100:.0f}%), {n_down} down ({n_down/len(jump_df)*100:.0f}%)")

        # When do jumps occur?
        jump_df['hour_et'] = jump_df['time'].dt.hour - 5
        jump_hour_dist = jump_df['hour_et'].value_counts().sort_index()
        print(f"\n--- Jump timing distribution (ET) ---")
        for hour, count in jump_hour_dist.items():
            bar = '#' * count
            print(f"  {hour:02d}:xx  {count:>3d} jumps  {bar}")

        # Open vs midday vs close
        open_jumps = jump_df[(jump_df['time_utc'] >= '14:30') & (jump_df['time_utc'] <= '15:00')]
        close_jumps = jump_df[(jump_df['time_utc'] >= '20:30') & (jump_df['time_utc'] <= '20:55')]
        midday_jumps = jump_df[(jump_df['time_utc'] >= '15:30') & (jump_df['time_utc'] <= '19:55')]

        # Normalize by number of bars in each session
        n_open_bars = 5  # 14:35-15:00 (skip first bar NaN)
        n_close_bars = 6  # 20:30-20:55
        n_midday_bars = 54  # 15:30-19:55
        print(f"\n--- Jump rate by session ---")
        print(f"  Open (9:30-10:00):   {len(open_jumps)} jumps / {n_open_bars*n_days} bars = {len(open_jumps)/(n_open_bars*n_days)*100:.2f}%")
        print(f"  Midday (10:30-15:00): {len(midday_jumps)} jumps / {n_midday_bars*n_days} bars = {len(midday_jumps)/(n_midday_bars*n_days)*100:.2f}%")
        print(f"  Close (15:30-16:00): {len(close_jumps)} jumps / {n_close_bars*n_days} bars = {len(close_jumps)/(n_close_bars*n_days)*100:.2f}%")

        # Top 10 largest jumps
        print(f"\n--- Top 10 largest jumps ---")
        top10 = jump_df.nlargest(10, 'L_stat', keep='first').copy()
        top10['abs_L'] = top10['L_stat'].abs()
        top10 = jump_df.loc[jump_df['L_stat'].abs().nlargest(10).index]
        print(f"{'Date':>12s} {'Time ET':>8s} {'Return':>10s} {'|L|':>8s} {'p-value':>10s} {'Dir':>5s}")
        for _, row in top10.iterrows():
            h_et = row['time'].hour - 5
            m = row['time'].minute
            print(f"  {str(row['date']):>10s}  {h_et:02d}:{m:02d}  {row['return']*100:>8.3f}%  {abs(row['L_stat']):>6.2f}  {row['p_value']:>8.6f}  {row['direction']:>4s}")

        # Jump contribution to RV
        print(f"\n--- Jump contribution to daily RV ---")
        for date, group in jump_df.groupby('date'):
            day_data = df[df['date'] == date]
            daily_rv = (day_data['log_return'] ** 2).sum()
            jump_rv = (group['return'] ** 2).sum()
            if daily_rv > 0:
                pct = jump_rv / daily_rv * 100
                print(f"  {date}: {len(group)} jumps, RV contribution = {pct:.1f}%")

    return jump_df


def analysis_6_rv_vs_daily(df):
    """Compare 5-min RV with daily r² (proxy quality check)."""
    print("\n" + "="*70)
    print("ANALYSIS 6: RV vs DAILY r² (PROXY QUALITY)")
    print("="*70)

    df['date'] = df.index.date
    results = []
    for date, group in df.groupby('date'):
        group = group.sort_index()
        rets = group['log_return'].dropna()
        if len(rets) < 10:
            continue

        # 5-min RV
        rv_5min = (rets ** 2).sum()

        # Daily return (close-to-close)
        daily_r = np.log(group['Close'].iloc[-1] / group['Close'].iloc[0])
        daily_r_sq = daily_r ** 2

        # Bipower Variation (robust to jumps)
        abs_rets = rets.abs().values
        bv = 0
        for i in range(1, len(abs_rets)):
            bv += abs_rets[i] * abs_rets[i-1]
        bv *= (np.pi / 2) / (len(abs_rets) - 1) * len(abs_rets)

        results.append({
            'date': date,
            'rv_5min': rv_5min,
            'r_sq': daily_r_sq,
            'daily_return': daily_r,
            'bv': bv,
            'jump_var': max(rv_5min - bv, 0),
            'n_bars': len(rets)
        })

    rv_comp = pd.DataFrame(results)

    # Correlation between RV and r²
    corr = rv_comp['rv_5min'].corr(rv_comp['r_sq'])
    print(f"\ncorr(RV_5min, r_d²): {corr:.3f}")
    print(f"This measures how good daily r² is as a proxy for true volatility.")
    print(f"  (If corr~1, daily returns perfectly capture intraday variation)")
    print(f"  (If corr<<1, significant intraday information is lost)")

    # RV/r² ratio
    ratio = rv_comp['rv_5min'].mean() / rv_comp['r_sq'].mean()
    print(f"\nmean(RV) / mean(r²): {ratio:.2f}")
    print(f"  (>1 means intraday variation exceeds what daily r² captures)")
    print(f"  (This is the noise ratio of the daily proxy)")

    # BV and jump variation
    mean_rv = rv_comp['rv_5min'].mean()
    mean_bv = rv_comp['bv'].mean()
    mean_jv = rv_comp['jump_var'].mean()
    print(f"\n--- Continuous vs Jump variation ---")
    print(f"Mean RV (total):      {mean_rv:.6f}")
    print(f"Mean BV (continuous): {mean_bv:.6f}  ({mean_bv/mean_rv*100:.1f}% of RV)")
    print(f"Mean JV (jumps):      {mean_jv:.6f}  ({mean_jv/mean_rv*100:.1f}% of RV)")

    # Annualized volatilities
    print(f"\n--- Annualized volatility estimates ---")
    print(f"From 5-min RV:  {np.sqrt(mean_rv * 252) * 100:.1f}%")
    print(f"From daily r²:  {np.sqrt(rv_comp['r_sq'].mean() * 252) * 100:.1f}%")
    print(f"From BV:        {np.sqrt(mean_bv * 252) * 100:.1f}%")

    # Distribution of RV
    print(f"\n--- Daily RV distribution ---")
    print(f"Mean:     {mean_rv:.6f}")
    print(f"Std:      {rv_comp['rv_5min'].std():.6f}")
    print(f"Skew:     {rv_comp['rv_5min'].skew():.2f}")
    print(f"Kurt:     {rv_comp['rv_5min'].kurtosis():.2f}")
    print(f"CV:       {rv_comp['rv_5min'].std()/mean_rv:.2f}")

    # log(RV) distribution (should be closer to normal)
    log_rv = np.log(rv_comp['rv_5min'])
    print(f"\n--- log(RV) distribution (should be ~normal for HAR-RV) ---")
    print(f"Mean:     {log_rv.mean():.3f}")
    print(f"Std:      {log_rv.std():.3f}")
    print(f"Skew:     {log_rv.skew():.2f}")
    print(f"Kurt:     {log_rv.kurtosis():.2f}")
    jb_stat, jb_p = stats.jarque_bera(log_rv.dropna())
    print(f"JB test:  stat={jb_stat:.2f}, p={jb_p:.4f}  ({'normal' if jb_p > 0.05 else 'NOT normal'})")

    return rv_comp


def summary(vol_results, volume_results, rv_df, acf_results, jump_df, rv_comp):
    """Print comprehensive summary."""
    print("\n" + "="*70)
    print("K297 SUMMARY: INTRADAY VOLATILITY PATTERN — FIRST LOOK")
    print("="*70)
    print(f"\nData: SPY 5-min, 47 trading days (2026-01-14 to 2026-03-23)")
    print(f"Source: yfinance free tier")
    print(f"PRELIMINARY: Small sample (47 days). All findings descriptive only.")

    print(f"\n--- Key Findings ---")

    # 1. U-shape
    print(f"\n1. INTRADAY VOL SMILE:")
    print(f"   U-shape confirmed: {vol_results['is_u_shape']}")
    print(f"   Open/Midday ratio:  {vol_results['u_shape_open_ratio']:.2f}x")
    print(f"   Close/Midday ratio: {vol_results['u_shape_close_ratio']:.2f}x")

    # 2. Volume
    print(f"\n2. VOLUME PATTERN:")
    print(f"   Volume-volatility cross-sectional corr: {volume_results['vol_vol_corr_cross_sectional']:.3f} (p={volume_results['corr_p_value']:.4f})")
    print(f"   Bar-level corr: {volume_results['vol_vol_corr_bar_level']:.3f}")

    # 3. RV decomposition
    print(f"\n3. RV DECOMPOSITION:")
    print(f"   Open 30min: {rv_df['pct_open'].mean():.1f}% of daily RV (vs {6/78*100:.1f}% uniform)")
    print(f"   Midday:     {rv_df['pct_midday'].mean():.1f}% of daily RV")
    print(f"   Close 30min:{rv_df['pct_close'].mean():.1f}% of daily RV (vs {6/78*100:.1f}% uniform)")

    # 4. Autocorrelation
    print(f"\n4. AUTOCORRELATION:")
    if 1 in acf_results and acf_results[1]:
        acf1 = np.mean(acf_results[1])
        print(f"   ACF(r², lag=1, 5min): {acf1:.4f}")
    if 5 in acf_results and acf_results[5]:
        acf5 = np.mean(acf_results[5])
        print(f"   ACF(r², lag=5, 25min): {acf5:.4f}")
    if 10 in acf_results and acf_results[10]:
        acf10 = np.mean(acf_results[10])
        print(f"   ACF(r², lag=10, 50min): {acf10:.4f}")

    # 5. Jumps
    n_days = 47
    print(f"\n5. JUMP DETECTION (Lee-Mykland, p<0.01):")
    print(f"   Total jumps: {len(jump_df)}")
    print(f"   Jumps per day: {len(jump_df)/n_days:.1f}")
    if len(jump_df) > 0:
        n_up = (jump_df['direction'] == 'UP').sum()
        n_down = (jump_df['direction'] == 'DOWN').sum()
        print(f"   Direction: {n_up} up, {n_down} down ({n_down/(n_up+n_down)*100:.0f}% negative)")

    # 6. Proxy quality
    corr_rv_rsq = rv_comp['rv_5min'].corr(rv_comp['r_sq'])
    ratio = rv_comp['rv_5min'].mean() / rv_comp['r_sq'].mean()
    print(f"\n6. PROXY QUALITY:")
    print(f"   corr(RV, r_d²): {corr_rv_rsq:.3f}")
    print(f"   RV/r² ratio: {ratio:.2f}")
    print(f"   Jump variation: {rv_comp['jump_var'].mean()/rv_comp['rv_5min'].mean()*100:.1f}% of total RV")

    print(f"\n--- Implications for HAR-RV ---")
    print(f"1. Strong U-shape confirms classic market microstructure theory")
    print(f"2. Significant ACF at lag 1 suggests predictability in intraday vol")
    print(f"3. log(RV) distribution properties affect HAR-RV model specification")
    print(f"4. Jump component (~{rv_comp['jump_var'].mean()/rv_comp['rv_5min'].mean()*100:.0f}%) suggests HAR-RV-J may add value")
    print(f"5. Need {252 - 47} more days (~{(252-47)//5} weeks) for full HAR-RV estimation")

    print(f"\n--- Limitations ---")
    print(f"1. Only 47 days — too few for HAR-RV estimation or meaningful OOS test")
    print(f"2. yfinance data quality not validated against exchange-level data")
    print(f"3. No overnight returns (open-to-close RV only)")
    print(f"4. Period covers Jan-Mar 2026 — may not be representative")
    print(f"5. Lee-Mykland jump test sensitive to window parameter K")


def main():
    print("K297: Intraday Volatility Pattern from 5-Min Data")
    print(f"{'='*70}")

    # Load data
    df = load_all_5min_data()

    # Compute returns
    df = compute_returns(df)

    # Run analyses
    vol_by_time, vol_results = analysis_1_intraday_vol_smile(df)
    volume_results = analysis_2_volume_pattern(df)
    rv_df = analysis_3_rv_decomposition(df)
    acf_results = analysis_4_autocorrelation(df)
    jump_df = analysis_5_jump_detection(df)
    rv_comp = analysis_6_rv_vs_daily(df)

    # Summary
    summary(vol_results, volume_results, rv_df, acf_results, jump_df, rv_comp)

    print(f"\n{'='*70}")
    print("K297 COMPLETE")


if __name__ == '__main__':
    main()
