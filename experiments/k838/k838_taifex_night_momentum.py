#!/usr/bin/env python3
"""
K838: TAIFEX Night Session Momentum Strategy
=============================================
Hypothesis: Night session (15:00-05:00) return predicts next day session direction,
            because night session covers full US trading hours.

Data: TAIFEX TX tick data (2017-05 to 2026-03), Big5 CSV
      Using TX1 files (near-month contract only) for liquidity

Strategies:
  S0: Buy-and-Hold day session
  S1: Night Momentum (sign of night return)
  S2: Night Momentum w/ threshold (|night_ret| > 0.5%)
  S3: Volume-weighted night momentum
  S4: Contrarian Gap (mean reversion on large overnight gaps)

Signal lag: night session t → day session t+1 (3.75h gap, but conceptually
            night ends ~05:00, day opens ~08:45 same calendar day)
            Actually: night return from file date D's night session (previous evening)
            predicts day return from the SAME file date D.
            This is NOT lookahead because night session (15:00 prev day - 05:00 today)
            ends BEFORE day session (08:45-13:45 today).

Error log rules applied:
- No lookahead: night session ends before day session opens
- Big5 encoding handling
- Near-month contract only (TX1 files)
- Skip files < 100 bytes

References:
- K817: US→Taiwan overnight gap captures 77-93% of alpha
- K812v2: Lead-lag direction only 50.2% with close-to-close returns
- Barclay & Hendershott (2003): Price discovery in after-hours trading

Author: VolPred Research System
Date: 2026-04-03
"""

import os
import glob
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from collections import defaultdict

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
TX_COST_PCT = 0.0001  # 1 bp round-trip (2 ticks on ~20000 index ≈ 0.01%)
MIN_FILE_SIZE = 100   # Skip files smaller than this
THRESHOLD_PCT = 0.005  # 0.5% for S2 threshold strategy
GAP_THRESHOLD = 0.003  # 0.3% for S4 contrarian gap

# ============================================================
# Step 1: Parse TX1 files to extract session prices
# ============================================================

def parse_tx1_file(filepath):
    """
    Parse a TX1 (near-month) file and extract:
    - night_open, night_close, night_volume (PM + AM portions)
    - day_open, day_close, day_volume

    Time boundaries:
    - Night PM: 150000 <= time <= 235959  (previous calendar day's evening)
    - Night AM: 0 <= time <= 50000        (early morning, same calendar day)
    - Day:      84500 <= time <= 134500

    Returns dict with session data, keyed by the file's trading date.
    """
    try:
        df = pd.read_csv(filepath, encoding='big5', dtype=str)
    except Exception:
        try:
            df = pd.read_csv(filepath, encoding='cp950', dtype=str)
        except Exception:
            return None

    if len(df) < 2:
        return None

    # Standardize column names
    cols = df.columns.tolist()
    if len(cols) < 6:
        return None

    # Parse numeric columns
    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df['volume'] = pd.to_numeric(df.iloc[:, 5], errors='coerce')
        df['date_str'] = df.iloc[:, 0].astype(str)
    except Exception:
        return None

    # Drop rows with NaN price
    df = df.dropna(subset=['price', 'time_int'])
    if len(df) == 0:
        return None

    # Classify sessions
    t = df['time_int'].values
    night_pm_mask = (t >= 150000) & (t <= 235959)
    night_am_mask = (t >= 0) & (t <= 50000)
    day_mask = (t >= 84500) & (t <= 134500)

    result = {}

    # Night session (PM + AM combined)
    night_mask = night_pm_mask | night_am_mask
    night_df = df[night_mask].copy()
    day_df = df[day_mask].copy()

    if len(night_df) >= 2:
        # Sort by PM first then AM (night PM has higher time values)
        # PM trades: 150000-235959, AM trades: 0-50000
        # We need chronological order: PM first, then AM
        night_pm = df[night_pm_mask]
        night_am = df[night_am_mask]

        if len(night_pm) > 0:
            night_open_price = night_pm['price'].iloc[0]
        elif len(night_am) > 0:
            night_open_price = night_am['price'].iloc[0]
        else:
            night_open_price = None

        if len(night_am) > 0:
            night_close_price = night_am['price'].iloc[-1]
        elif len(night_pm) > 0:
            night_close_price = night_pm['price'].iloc[-1]
        else:
            night_close_price = None

        night_vol = night_df['volume'].sum()

        if night_open_price is not None and night_close_price is not None:
            result['night_open'] = float(night_open_price)
            result['night_close'] = float(night_close_price)
            result['night_volume'] = float(night_vol)

    if len(day_df) >= 2:
        result['day_open'] = float(day_df['price'].iloc[0])
        result['day_close'] = float(day_df['price'].iloc[-1])
        result['day_volume'] = float(day_df['volume'].sum())

    return result


def load_all_tx1_data():
    """Load all TX1 files and build daily session price dataframe."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    files = sorted(glob.glob(pattern))

    print(f"Found {len(files)} TX1 files")

    records = []
    skipped = 0
    errors = 0

    for i, filepath in enumerate(files):
        if os.path.getsize(filepath) < MIN_FILE_SIZE:
            skipped += 1
            continue

        # Extract date from filename: Daily_YYYY_MM_DDTX1.csv
        basename = os.path.basename(filepath)
        try:
            parts = basename.replace("Daily_", "").replace("TX1.csv", "").split("_")
            date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
            file_date = pd.Timestamp(date_str)
        except Exception:
            errors += 1
            continue

        data = parse_tx1_file(filepath)
        if data is None:
            errors += 1
            continue

        data['date'] = file_date
        records.append(data)

        if (i + 1) % 500 == 0:
            print(f"  Processed {i+1}/{len(files)} files...")

    print(f"  Loaded: {len(records)}, Skipped: {skipped}, Errors: {errors}")

    df = pd.DataFrame(records)
    df = df.set_index('date').sort_index()
    return df


# ============================================================
# Step 2: Calculate returns
# ============================================================

def calculate_returns(df):
    """Calculate night, day, and gap returns."""
    # Night return: from night open to night close
    mask = df['night_open'].notna() & df['night_close'].notna() & (df['night_open'] > 0)
    df.loc[mask, 'night_return'] = (df.loc[mask, 'night_close'] - df.loc[mask, 'night_open']) / df.loc[mask, 'night_open']

    # Day return: from day open to day close
    mask = df['day_open'].notna() & df['day_close'].notna() & (df['day_open'] > 0)
    df.loc[mask, 'day_return'] = (df.loc[mask, 'day_close'] - df.loc[mask, 'day_open']) / df.loc[mask, 'day_open']

    # Overnight gap: from night close to day open
    mask = df['night_close'].notna() & df['day_open'].notna() & (df['night_close'] > 0)
    df.loc[mask, 'overnight_gap'] = (df.loc[mask, 'day_open'] - df.loc[mask, 'night_close']) / df.loc[mask, 'night_close']

    return df


# ============================================================
# Step 3: Strategy signals
# ============================================================

def generate_signals(df):
    """
    Generate trading signals.

    CRITICAL: The night session in file date D covers:
    - PM of day D-1 (15:00-23:59)
    - AM of day D (00:00-05:00)
    The day session in file date D covers: 08:45-13:45 of day D.

    So night_return from file D ends at ~05:00 on day D,
    and day_return from file D starts at ~08:45 on day D.
    Night ends BEFORE day starts on the SAME file date.

    This means: night_return[D] can predict day_return[D] without lookahead,
    because night session closes 3.75 hours before day session opens.

    However, to be conservative and account for execution realities,
    we ALSO test with shift(1) as a robustness check.
    """
    # S1: Night Momentum (same-day, no shift needed since night ends before day)
    df['signal_s1'] = np.sign(df['night_return'])

    # S2: Night Momentum with threshold
    df['signal_s2'] = 0.0
    mask_up = df['night_return'] > THRESHOLD_PCT
    mask_dn = df['night_return'] < -THRESHOLD_PCT
    df.loc[mask_up, 'signal_s2'] = 1.0
    df.loc[mask_dn, 'signal_s2'] = -1.0

    # S3: Volume-weighted momentum
    # Normalize night volume to [0, 1] using rolling percentile
    if 'night_volume' in df.columns:
        vol_rank = df['night_volume'].rolling(252, min_periods=60).rank(pct=True)
        df['signal_s3'] = np.sign(df['night_return']) * vol_rank
    else:
        df['signal_s3'] = df['signal_s1']

    # S4: Contrarian Gap
    df['signal_s4'] = 0.0
    gap_up = df['overnight_gap'] > GAP_THRESHOLD
    gap_dn = df['overnight_gap'] < -GAP_THRESHOLD
    df.loc[gap_up, 'signal_s4'] = -1.0  # Gap up → expect mean reversion → short
    df.loc[gap_dn, 'signal_s4'] = 1.0   # Gap down → expect mean reversion → long

    # S1_lag: Shifted version (previous day's night predicts today's day)
    df['signal_s1_lag'] = np.sign(df['night_return']).shift(1)

    return df


# ============================================================
# Step 4: Backtest
# ============================================================

def backtest_strategy(df, signal_col, return_col='day_return', name='Strategy'):
    """Backtest a strategy and return performance metrics."""
    valid = df[[signal_col, return_col]].dropna()
    if len(valid) < 100:
        return None

    signals = valid[signal_col].values
    returns = valid[return_col].values

    # Strategy return = signal * day_return - TX cost when signal changes
    signal_changes = np.abs(np.diff(signals, prepend=signals[0]))
    # TX cost only when position changes (and signal != 0)
    tx_costs = signal_changes * TX_COST_PCT

    strat_returns = signals * returns - tx_costs

    # Metrics
    n_trades = np.sum(signal_changes > 0)
    n_days = len(strat_returns)

    cum_ret = np.cumprod(1 + strat_returns)
    total_return = cum_ret[-1] / cum_ret[0] - 1

    ann_return = np.mean(strat_returns) * 252
    ann_vol = np.std(strat_returns) * np.sqrt(252)
    sharpe = ann_return / ann_vol if ann_vol > 0 else 0

    # Max Drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns)

    # Hit rate (direction accuracy)
    if signal_col in ['signal_s2', 'signal_s4']:
        # For threshold strategies, only count days with signals
        active = signals != 0
        if np.sum(active) > 0:
            correct = (signals[active] * returns[active]) > 0
            hit_rate = np.mean(correct)
            active_days = np.sum(active)
        else:
            hit_rate = np.nan
            active_days = 0
    else:
        active = signals != 0
        if np.sum(active) > 0:
            correct = (signals[active] * returns[active]) > 0
            hit_rate = np.mean(correct)
            active_days = np.sum(active)
        else:
            hit_rate = np.nan
            active_days = 0

    # Annual breakdown
    valid_with_strat = valid.copy()
    valid_with_strat['strat_return'] = strat_returns
    yearly = valid_with_strat.groupby(valid_with_strat.index.year)['strat_return'].agg(
        ['mean', 'std', 'count']
    )
    yearly['ann_return'] = yearly['mean'] * 252
    yearly['ann_vol'] = yearly['std'] * np.sqrt(252)
    yearly['sharpe'] = yearly['ann_return'] / yearly['ann_vol']

    return {
        'name': name,
        'n_days': int(n_days),
        'active_days': int(active_days),
        'n_trades': int(n_trades),
        'ann_return': round(float(ann_return), 6),
        'ann_vol': round(float(ann_vol), 6),
        'sharpe': round(float(sharpe), 4),
        'max_dd': round(float(max_dd), 4),
        'hit_rate': round(float(hit_rate), 4) if not np.isnan(hit_rate) else None,
        'total_return': round(float(total_return), 4),
        'yearly': {str(y): {
            'sharpe': round(float(row['sharpe']), 4),
            'ann_return': round(float(row['ann_return']), 6),
            'count': int(row['count'])
        } for y, row in yearly.iterrows()}
    }


def dm_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    e1, e2: forecast errors (or loss differentials)
    Returns: DM statistic and p-value
    """
    from scipy import stats
    d = e1 - e2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West variance estimate
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += gamma_k

    var_d = (gamma_0 + 2 * gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n-1))

    return round(float(dm_stat), 4), round(float(p_value), 6)


# ============================================================
# Main execution
# ============================================================

def main():
    print("=" * 70)
    print("K838: TAIFEX Night Session Momentum Strategy")
    print("=" * 70)

    # Load data
    print("\n[Step 1] Loading TX1 data...")
    t0 = datetime.now()
    df = load_all_tx1_data()
    t1 = datetime.now()
    print(f"  Data loaded in {(t1-t0).seconds}s, shape: {df.shape}")
    print(f"  Date range: {df.index.min()} to {df.index.max()}")

    # Calculate returns
    print("\n[Step 2] Calculating returns...")
    df = calculate_returns(df)

    # Drop rows without both night and day returns
    valid = df.dropna(subset=['night_return', 'day_return'])
    print(f"  Valid days with both night & day returns: {len(valid)}")
    print(f"  Period: {valid.index.min()} to {valid.index.max()}")

    # Descriptive statistics
    print("\n[Step 2b] Descriptive Statistics:")
    for col in ['night_return', 'day_return', 'overnight_gap']:
        s = valid[col].dropna()
        print(f"  {col}:")
        print(f"    Mean:   {s.mean()*100:.4f}%")
        print(f"    Std:    {s.std()*100:.4f}%")
        print(f"    Skew:   {s.skew():.4f}")
        print(f"    Kurt:   {s.kurtosis():.4f}")
        print(f"    Min:    {s.min()*100:.4f}%")
        print(f"    Max:    {s.max()*100:.4f}%")

    # Correlation analysis
    print("\n[Step 2c] Correlation Analysis:")
    corr_night_day = valid['night_return'].corr(valid['day_return'])
    corr_night_day_lag = valid['night_return'].corr(valid['day_return'].shift(-1))
    corr_gap_day = valid['overnight_gap'].corr(valid['day_return'])

    from scipy import stats
    # Spearman rank correlation
    spear_night_day, spear_p = stats.spearmanr(
        valid['night_return'].dropna(),
        valid.loc[valid['night_return'].notna(), 'day_return']
    )

    print(f"  Pearson corr(night_ret, day_ret):        {corr_night_day:.4f}")
    print(f"  Spearman corr(night_ret, day_ret):       {spear_night_day:.4f} (p={spear_p:.4e})")
    print(f"  Pearson corr(night_ret, next_day_ret):   {corr_night_day_lag:.4f}")
    print(f"  Pearson corr(overnight_gap, day_ret):    {corr_gap_day:.4f}")

    # Direction agreement
    same_dir = np.mean(np.sign(valid['night_return']) == np.sign(valid['day_return']))
    print(f"  Direction agreement (night→same day):    {same_dir:.4f} ({same_dir*100:.1f}%)")

    same_dir_lag = valid.dropna(subset=['night_return'])
    nr = same_dir_lag['night_return'].values[:-1]
    dr = same_dir_lag['day_return'].values[1:]
    same_dir_lag_pct = np.mean(np.sign(nr) == np.sign(dr))
    print(f"  Direction agreement (night→next day):    {same_dir_lag_pct:.4f} ({same_dir_lag_pct*100:.1f}%)")

    # Generate signals
    print("\n[Step 3] Generating signals...")
    df = generate_signals(df)

    # Backtest all strategies
    print("\n[Step 4] Backtesting strategies...")
    strategies = {
        'S0: Buy-and-Hold Day': ('signal_s0', 'Buy-and-Hold day session'),
        'S1: Night Momentum': ('signal_s1', 'Night Momentum (same-day)'),
        'S1_lag: Night Momentum (lagged)': ('signal_s1_lag', 'Night Momentum (t-1 night → t day)'),
        'S2: Threshold Momentum': ('signal_s2', 'Threshold (|night_ret|>0.5%)'),
        'S3: Volume-Weighted': ('signal_s3', 'Volume-Weighted Momentum'),
        'S4: Contrarian Gap': ('signal_s4', 'Contrarian Gap (>0.3%)'),
    }

    # Add S0 (buy-and-hold)
    df['signal_s0'] = 1.0

    results = {}
    for key, (signal_col, name) in strategies.items():
        res = backtest_strategy(df, signal_col, name=name)
        if res:
            results[key] = res
            print(f"\n  {name}:")
            print(f"    Sharpe:    {res['sharpe']:.4f}")
            print(f"    Ann Ret:   {res['ann_return']*100:.2f}%")
            print(f"    Ann Vol:   {res['ann_vol']*100:.2f}%")
            print(f"    Max DD:    {res['max_dd']*100:.2f}%")
            print(f"    Hit Rate:  {res['hit_rate']}")
            print(f"    Active:    {res['active_days']}/{res['n_days']} days")

    # DM tests
    print("\n[Step 4b] Diebold-Mariano Tests (vs Buy-and-Hold):")
    bh_valid = df[['signal_s0', 'day_return']].dropna()
    bh_returns = (bh_valid['signal_s0'] * bh_valid['day_return']).values
    bh_sq_errors = bh_returns ** 2  # Using squared returns as loss

    dm_results = {}
    for key, (signal_col, name) in strategies.items():
        if key == 'S0: Buy-and-Hold Day':
            continue
        strat_valid = df[[signal_col, 'day_return']].dropna()
        # Align indices
        common_idx = bh_valid.index.intersection(strat_valid.index)
        if len(common_idx) < 100:
            continue

        bh_r = (df.loc[common_idx, 'signal_s0'] * df.loc[common_idx, 'day_return']).values
        st_r = (df.loc[common_idx, signal_col] * df.loc[common_idx, 'day_return']).values

        # Loss = negative return (we want higher returns)
        dm_stat, dm_p = dm_test(-st_r, -bh_r)
        dm_results[key] = {'dm_stat': dm_stat, 'p_value': dm_p}
        harvey_sig = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 2.0 else ("*" if abs(dm_stat) > 1.5 else ""))
        print(f"  {name}: DM={dm_stat:.4f}, p={dm_p:.6f} {harvey_sig}")

    # Yearly stability analysis for S1
    print("\n[Step 5] Yearly Performance (S1: Night Momentum):")
    if 'S1: Night Momentum' in results:
        yearly = results['S1: Night Momentum']['yearly']
        print(f"  {'Year':<6} {'Sharpe':>8} {'Ann Ret':>10} {'N days':>8}")
        for year in sorted(yearly.keys()):
            y = yearly[year]
            print(f"  {year:<6} {y['sharpe']:>8.4f} {y['ann_return']*100:>9.2f}% {y['count']:>8}")

    # Night volume vs signal reliability
    print("\n[Step 6] Night Volume Quintile Analysis:")
    vol_df = df.dropna(subset=['night_return', 'day_return', 'night_volume']).copy()
    if len(vol_df) > 200:
        vol_df['vol_quintile'] = pd.qcut(vol_df['night_volume'], 5, labels=['Q1(low)', 'Q2', 'Q3', 'Q4', 'Q5(high)'])
        for q in ['Q1(low)', 'Q2', 'Q3', 'Q4', 'Q5(high)']:
            qdf = vol_df[vol_df['vol_quintile'] == q]
            correct = np.mean(np.sign(qdf['night_return']) == np.sign(qdf['day_return']))
            avg_night = qdf['night_return'].mean() * 100
            avg_day = qdf['day_return'].mean() * 100
            corr_q = qdf['night_return'].corr(qdf['day_return'])
            print(f"  {q}: hit_rate={correct:.4f}, corr={corr_q:.4f}, avg_night={avg_night:.3f}%, avg_day={avg_day:.3f}%, n={len(qdf)}")

    # Regime analysis (VIX-like: by night session volatility)
    print("\n[Step 7] Regime Analysis (by night return magnitude):")
    regime_df = df.dropna(subset=['night_return', 'day_return']).copy()
    regime_df['night_abs'] = regime_df['night_return'].abs()
    regime_df['regime'] = pd.qcut(regime_df['night_abs'], 3, labels=['Low Vol', 'Med Vol', 'High Vol'])
    for reg in ['Low Vol', 'Med Vol', 'High Vol']:
        rdf = regime_df[regime_df['regime'] == reg]
        correct = np.mean(np.sign(rdf['night_return']) == np.sign(rdf['day_return']))
        corr_r = rdf['night_return'].corr(rdf['day_return'])
        s1_ret = (np.sign(rdf['night_return']) * rdf['day_return']).mean() * 252
        print(f"  {reg}: hit_rate={correct:.4f}, corr={corr_r:.4f}, S1_ann_ret={s1_ret*100:.2f}%, n={len(rdf)}")

    # Settlement day effect
    print("\n[Step 8] Settlement Day Analysis:")
    # 3rd Wednesday of each month
    from pandas.tseries.offsets import WeekOfMonth
    settle_dates = pd.date_range(start=df.index.min(), end=df.index.max(), freq=WeekOfMonth(week=2, weekday=2))
    settle_mask = df.index.isin(settle_dates)
    normal_mask = ~settle_mask

    for label, mask in [("Settlement days", settle_mask), ("Normal days", normal_mask)]:
        sub = df[mask].dropna(subset=['night_return', 'day_return'])
        if len(sub) > 10:
            correct = np.mean(np.sign(sub['night_return']) == np.sign(sub['day_return']))
            corr_s = sub['night_return'].corr(sub['day_return'])
            print(f"  {label}: n={len(sub)}, hit_rate={correct:.4f}, corr={corr_s:.4f}")

    # ============================================================
    # Compile final results
    # ============================================================

    final_results = {
        "experiment_id": "K838",
        "title": "TAIFEX Night Session Momentum Strategy",
        "date": "2026-04-03",
        "data_source": "TAIFEX TX tick data (TX1 near-month files)",
        "data_period": f"{valid.index.min().strftime('%Y-%m-%d')} to {valid.index.max().strftime('%Y-%m-%d')}",
        "n_trading_days": int(len(valid)),
        "hypothesis": "Night session (15:00-05:00) return predicts same-day day session direction",
        "descriptive_stats": {
            "night_return": {
                "mean_pct": round(valid['night_return'].mean() * 100, 4),
                "std_pct": round(valid['night_return'].std() * 100, 4),
                "skew": round(float(valid['night_return'].skew()), 4),
                "kurtosis": round(float(valid['night_return'].kurtosis()), 4),
            },
            "day_return": {
                "mean_pct": round(valid['day_return'].mean() * 100, 4),
                "std_pct": round(valid['day_return'].std() * 100, 4),
                "skew": round(float(valid['day_return'].skew()), 4),
                "kurtosis": round(float(valid['day_return'].kurtosis()), 4),
            },
            "overnight_gap": {
                "mean_pct": round(valid['overnight_gap'].mean() * 100, 4),
                "std_pct": round(valid['overnight_gap'].std() * 100, 4),
            }
        },
        "correlation": {
            "pearson_night_day": round(float(corr_night_day), 4),
            "spearman_night_day": round(float(spear_night_day), 4),
            "spearman_p_value": round(float(spear_p), 6),
            "pearson_night_nextday": round(float(corr_night_day_lag), 4),
            "pearson_gap_day": round(float(corr_gap_day), 4),
            "direction_agreement_same_day": round(float(same_dir), 4),
            "direction_agreement_next_day": round(float(same_dir_lag_pct), 4),
        },
        "strategy_results": results,
        "dm_tests_vs_bh": dm_results,
        "references": [
            "K817: US→Taiwan overnight gap captures 77-93% of alpha",
            "K812v2: Lead-lag direction only 50.2% with close-to-close returns",
            "Barclay & Hendershott (2003): Price discovery in after-hours trading",
            "Berkman et al. (2012): Overnight vs intraday returns"
        ],
        "conclusion": "",  # Will be filled after seeing results
        "limitations": [
            "TX cost assumption 1bp may be optimistic for retail (spread + slippage)",
            "Near-month rollover not modeled (using TX1 files directly)",
            "Night session liquidity varies (thin ~01:00-04:00)",
            "No margin/leverage modeling",
            "Signal is same-calendar-day (night ends 05:00, day starts 08:45)"
        ]
    }

    # Write conclusion based on results
    s1_res = results.get('S1: Night Momentum', {})
    s1_sharpe = s1_res.get('sharpe', 0)
    s1_hit = s1_res.get('hit_rate', 0)
    bh_sharpe = results.get('S0: Buy-and-Hold Day', {}).get('sharpe', 0)

    conclusion_parts = []
    conclusion_parts.append(f"Night→day direction agreement: {same_dir*100:.1f}% (Pearson r={corr_night_day:.4f}, Spearman r={spear_night_day:.4f})")

    if s1_hit and s1_hit > 0.52:
        conclusion_parts.append(f"S1 Night Momentum hit rate {s1_hit*100:.1f}% is above coin-flip")
    else:
        conclusion_parts.append(f"S1 Night Momentum hit rate {(s1_hit or 0)*100:.1f}% is near coin-flip")

    conclusion_parts.append(f"S1 Sharpe={s1_sharpe:.4f} vs BH Sharpe={bh_sharpe:.4f}")

    # Check DM significance
    s1_dm = dm_results.get('S1: Night Momentum', {})
    if abs(s1_dm.get('dm_stat', 0)) > 3.0:
        conclusion_parts.append("DM test: statistically significant (Harvey t>3.0)")
    else:
        conclusion_parts.append(f"DM test: NOT significant (|t|={abs(s1_dm.get('dm_stat', 0)):.2f} < 3.0)")

    final_results['conclusion'] = " | ".join(conclusion_parts)

    # Save results
    results_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "k838_taifex_night_momentum_results.json"
    )
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(final_results, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'='*70}")
    print(f"CONCLUSION: {final_results['conclusion']}")
    print(f"{'='*70}")
    print(f"\nResults saved to: {results_path}")

    return final_results


if __name__ == "__main__":
    results = main()
