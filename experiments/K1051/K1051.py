"""
K1051: Taiwan TX Futures Overnight Gap Strategy (SPY-conditioned)

Research question: Can the overnight gap alpha found in K515 (SPY-conditioned
10.73bp/day, t=4.06) be profitably traded using TX futures (2-3bp cost) instead
of ETF (18.55bp cost that killed the strategy)?

Data sources:
- TAIFEX tick data: ~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/Daily_YYYY_MM_DDTX.csv
- SPY/VIX daily: yfinance

Method:
1. Build daily open/close from TX tick data (most active contract by volume)
2. Calculate overnight gap returns
3. SPY-conditioned strategy: if SPY_{t-1} > 0, go long overnight
4. TX futures cost: 2bp per round trip (conservative)

References:
- K515: Overnight gap alpha (SPY-conditioned 10.73bp/day, t=4.06)
- TAIFEX format: Big5, 9 cols (2012) / 10 cols (2014+)
- Night session: started ~2017-05-22, 15:00-05:00 next day

Author: VolPred Research System
"""

import os
import glob
import json
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# CONFIG
# ============================================================
TAIFEX_DIR = os.path.expanduser("~/Dropbox/TAIFEXDATA/TAIFEXDATA/python")
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
TX_COST_BP = 2.0  # 2bp round-trip cost for TX futures
NIGHT_SESSION_START_DATE = "2017-05-22"  # Night session started around this date

# ============================================================
# STEP 1: Parse TAIFEX TX tick data -> daily OHLC
# ============================================================

def read_tx_file(filepath):
    """Read a single TX file, handle Big5 encoding and column format changes."""
    try:
        # Try Big5 first, then utf-8
        for enc in ['big5', 'utf-8', 'cp950']:
            try:
                df = pd.read_csv(filepath, encoding=enc)
                break
            except (UnicodeDecodeError, UnicodeError):
                continue
        else:
            return None

        # Detect column format by header
        cols = df.columns.tolist()

        # Standardize column names
        col_map = {}
        for c in cols:
            if '成交日期' in c:
                col_map[c] = 'date'
            elif '商品代號' in c:
                col_map[c] = 'product'
            elif '到期月份' in c:
                col_map[c] = 'contract_month'
            elif '成交時間' in c:
                col_map[c] = 'time'
            elif '成交價格' in c:
                col_map[c] = 'price'
            elif '成交數量' in c:
                col_map[c] = 'volume'

        df = df.rename(columns=col_map)

        # Filter only TX product
        if 'product' in df.columns:
            df = df[df['product'].astype(str).str.strip() == 'TX']

        # Convert types
        df['date'] = df['date'].astype(int)
        df['time'] = pd.to_numeric(df['time'], errors='coerce')
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

        # Drop invalid rows
        df = df.dropna(subset=['date', 'time', 'price', 'volume'])
        df = df[df['price'] > 0]
        df = df[df['volume'] > 0]

        return df[['date', 'contract_month', 'time', 'price', 'volume']]

    except Exception as e:
        return None


def get_most_active_contract(df_day):
    """Select the most active contract month by total volume for a given day."""
    vol_by_contract = df_day.groupby('contract_month')['volume'].sum()
    if len(vol_by_contract) == 0:
        return None
    return vol_by_contract.idxmax()


def extract_daily_ohlc(df, trading_date_int):
    """
    Extract day session open/close and night session close for a given trading date.

    Day session: 08:45 (84500) - 13:45 (134500)
    Night session: 15:00 (150000) - 05:00 next day (50000)

    The night session ticks for date D appear as:
    - date=D, time=150000-235959 (same calendar day)
    - date=D+1_trading_date, time=0-50000 (next calendar day, but attributed to next trading date)

    Actually based on our data analysis:
    - In file Daily_YYYY_MM_DDTX.csv:
      - Previous day's night session: date=prev_day, time=150000-235959
      - Current day's early morning (continuation of night): date=current_day, time=0-50000
      - Current day's day session: date=current_day, time=84500-134500
    """
    df_date = df[df['date'] == trading_date_int]
    if len(df_date) == 0:
        return None

    # Select most active contract
    active_contract = get_most_active_contract(df_date)
    if active_contract is None:
        return None

    df_active = df_date[df_date['contract_month'] == active_contract].copy()
    df_active = df_active.sort_values('time')

    # Day session: 84500-134500
    day_ticks = df_active[(df_active['time'] >= 84500) & (df_active['time'] <= 134500)]

    # Night session for this trading date: time >= 150000 (same day)
    # Note: early morning continuation (time < 50000) will be in next day's date
    night_ticks = df_active[df_active['time'] >= 150000]

    # Early morning ticks (continuation of PREVIOUS night session): time < 50000
    early_morning_ticks = df_active[df_active['time'] < 50000]

    result = {
        'trading_date': trading_date_int,
        'contract_month': active_contract,
    }

    if len(day_ticks) > 0:
        result['day_open'] = day_ticks.iloc[0]['price']
        result['day_close'] = day_ticks.iloc[-1]['price']
        result['day_volume'] = day_ticks['volume'].sum()

    if len(night_ticks) > 0:
        result['night_open'] = night_ticks.iloc[0]['price']
        result['night_last_before_midnight'] = night_ticks.iloc[-1]['price']
        result['night_volume_before_midnight'] = night_ticks['volume'].sum()

    if len(early_morning_ticks) > 0:
        result['early_morning_close'] = early_morning_ticks.iloc[-1]['price']
        result['early_morning_volume'] = early_morning_ticks['volume'].sum()

    return result


def build_daily_data():
    """Build daily OHLC dataset from all TX files."""
    print("Building daily OHLC from TAIFEX tick data...")

    # Get all TX files (not TX1, TX2)
    pattern = os.path.join(TAIFEX_DIR, "Daily_*TX.csv")
    files = sorted(glob.glob(pattern))

    # Filter out TX1, TX2, etc.
    tx_files = [f for f in files if f.endswith("TX.csv") and not any(
        f.endswith(f"TX{i}.csv") for i in range(1, 10)
    )]

    print(f"Found {len(tx_files)} TX files")

    all_records = []

    for i, filepath in enumerate(tx_files):
        if i % 500 == 0:
            print(f"  Processing file {i}/{len(tx_files)}...")

        df = read_tx_file(filepath)
        if df is None or len(df) == 0:
            continue

        # Get unique trading dates in this file
        unique_dates = df['date'].unique()

        for td in unique_dates:
            record = extract_daily_ohlc(df, td)
            if record is not None:
                record['source_file'] = os.path.basename(filepath)
                all_records.append(record)

    if len(all_records) == 0:
        raise ValueError("No records extracted from TAIFEX data!")

    # Convert to DataFrame
    daily_df = pd.DataFrame(all_records)

    # For each trading_date, we might have records from multiple files
    # (night session in one file, day session in another)
    # Aggregate by trading_date
    print(f"Raw records: {len(daily_df)}")

    # Group by trading_date: combine day session and night session info
    agg_records = []
    for td, group in daily_df.groupby('trading_date'):
        rec = {'trading_date': td}

        # Day session info
        day_rows = group.dropna(subset=['day_open']) if 'day_open' in group.columns else pd.DataFrame()
        if 'day_open' in group.columns:
            day_rows = group[group['day_open'].notna()]

        if len(day_rows) > 0:
            # Use the row with most day volume
            best_day = day_rows.loc[day_rows.get('day_volume', pd.Series([0]*len(day_rows))).idxmax()]
            rec['day_open'] = best_day.get('day_open')
            rec['day_close'] = best_day.get('day_close')
            rec['day_volume'] = best_day.get('day_volume', 0)

        # Night session info (last part before midnight from same trading date)
        if 'night_last_before_midnight' in group.columns:
            night_rows = group[group['night_last_before_midnight'].notna()]
            if len(night_rows) > 0:
                best_night = night_rows.iloc[-1]
                rec['night_open'] = best_night.get('night_open')
                rec['night_last_before_midnight'] = best_night.get('night_last_before_midnight')

        # Early morning close (continuation from previous night, appears as current date)
        if 'early_morning_close' in group.columns:
            em_rows = group[group['early_morning_close'].notna()]
            if len(em_rows) > 0:
                rec['early_morning_close'] = em_rows.iloc[-1]['early_morning_close']

        agg_records.append(rec)

    result_df = pd.DataFrame(agg_records)

    # Convert trading_date to datetime
    result_df['date'] = pd.to_datetime(result_df['trading_date'].astype(str), format='%Y%m%d')
    result_df = result_df.sort_values('date').reset_index(drop=True)

    print(f"Aggregated daily records: {len(result_df)}")
    print(f"Date range: {result_df['date'].min()} to {result_df['date'].max()}")

    return result_df


def compute_overnight_gap(daily_df):
    """
    Compute overnight gap returns.

    For night-session era (post 2017-05-22):
      overnight_gap_t = (day_open_t - night_close_{t-1}) / night_close_{t-1}
      where night_close = early_morning_close (05:00) of the SAME calendar file
      but attributed to previous trading date's night session

    For pre-night-session era:
      overnight_gap_t = (day_open_t - day_close_{t-1}) / day_close_{t-1}

    The key insight: In the file structure, the "early_morning_close" for trading_date D
    is actually the close of the night session that STARTED on trading_date D-1.

    So for a given date D:
    - Previous close = early_morning_close of D (if exists, this is D-1's night session end)
                       OR day_close of D-1 (if no night session)
    - Day open = day_open of D
    - Gap = (day_open_D - previous_close) / previous_close
    """

    daily_df = daily_df.copy()
    night_start = pd.Timestamp(NIGHT_SESSION_START_DATE)

    gaps = []

    for i in range(1, len(daily_df)):
        row = daily_df.iloc[i]
        prev_row = daily_df.iloc[i-1]

        day_open = row.get('day_open')
        if pd.isna(day_open):
            continue

        # Determine previous close
        if row['date'] >= night_start:
            # Night session era: use early_morning_close of current date
            # (this is actually the end of previous trading date's night session)
            prev_close = row.get('early_morning_close')
            if pd.isna(prev_close):
                # Fallback: use previous day's night_last_before_midnight
                prev_close = prev_row.get('night_last_before_midnight')
            if pd.isna(prev_close):
                # Fallback: use previous day's day_close
                prev_close = prev_row.get('day_close')
        else:
            # Pre-night session: use previous day's day_close
            prev_close = prev_row.get('day_close')

        if pd.isna(prev_close) or prev_close <= 0:
            continue

        gap_return = (day_open - prev_close) / prev_close

        gaps.append({
            'date': row['date'],
            'day_open': day_open,
            'prev_close': prev_close,
            'gap_return': gap_return,
            'day_close': row.get('day_close'),
            'has_night_session': row['date'] >= night_start
        })

    gap_df = pd.DataFrame(gaps)
    gap_df['date'] = pd.to_datetime(gap_df['date'])

    print(f"\nOvernight gap data: {len(gap_df)} observations")
    print(f"  Pre-night session: {(~gap_df['has_night_session']).sum()}")
    print(f"  Post-night session: {gap_df['has_night_session'].sum()}")

    return gap_df


# ============================================================
# STEP 2: Get SPY data
# ============================================================

def get_spy_data():
    """Download SPY daily returns from yfinance."""
    import yfinance as yf

    print("\nDownloading SPY data from yfinance...")
    spy = yf.download("SPY", start="2011-12-01", end="2026-12-31", progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    spy['spy_return'] = spy['Close'].pct_change()
    spy = spy[['Close', 'spy_return']].dropna()
    spy.index = spy.index.tz_localize(None)
    spy = spy.rename(columns={'Close': 'spy_close'})

    print(f"SPY data: {len(spy)} observations, {spy.index.min()} to {spy.index.max()}")
    return spy


def get_vix_data():
    """Download VIX daily data from yfinance."""
    import yfinance as yf

    print("Downloading VIX data from yfinance...")
    vix = yf.download("^VIX", start="2011-12-01", end="2026-12-31", progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix = vix[['Close']].rename(columns={'Close': 'vix'})
    vix.index = vix.index.tz_localize(None)

    print(f"VIX data: {len(vix)} observations")
    return vix


# ============================================================
# STEP 3: Merge and build strategy signals
# ============================================================

def build_strategy_data(gap_df, spy_df, vix_df):
    """Merge gap returns with SPY signal data."""

    # Taiwan is 1 day ahead of US in calendar terms
    # SPY trades Monday-Friday US time
    # Taiwan trades Monday-Friday Taiwan time
    # When Taiwan opens at 08:45, yesterday's SPY close is known
    # So for Taiwan date D, we use SPY return from US date D-1 (or the last US trading day before D)

    # Create a mapping: for each Taiwan trading date, find the most recent SPY trading day BEFORE it
    gap_df = gap_df.copy()
    spy_df = spy_df.copy()

    # SPY signal: shift by 1 to avoid lookahead
    # For Taiwan date D, we use SPY return from the LAST US trading day that is BEFORE Taiwan date D
    # Taiwan date D opens at 08:45 Taiwan time = 20:45 US ET on D-1 (or 00:45 on D for summer)
    # So SPY data from D-1 (US) is available

    # Simple approach: for each gap date, find the most recent SPY date that is strictly before it
    spy_dates = spy_df.index.sort_values()

    merged_records = []
    for _, row in gap_df.iterrows():
        tw_date = row['date']

        # Find most recent SPY date before Taiwan date
        # (Taiwan opens 08:45 local = previous US day evening, so D-1 US data is available)
        spy_before = spy_dates[spy_dates < tw_date]
        if len(spy_before) == 0:
            continue

        last_spy_date = spy_before[-1]
        spy_row = spy_df.loc[last_spy_date]

        # Also get VIX
        vix_before = vix_df.index[vix_df.index < tw_date]
        vix_val = vix_df.loc[vix_before[-1], 'vix'] if len(vix_before) > 0 else np.nan

        rec = row.to_dict()
        rec['spy_date'] = last_spy_date
        rec['spy_return'] = spy_row['spy_return']
        rec['spy_close'] = spy_row['spy_close']
        rec['vix'] = vix_val
        merged_records.append(rec)

    merged_df = pd.DataFrame(merged_records)
    print(f"\nMerged dataset: {len(merged_df)} observations")

    return merged_df


# ============================================================
# STEP 4: Strategy evaluation
# ============================================================

def evaluate_strategy(df, signal_col, strategy_name, cost_bp=TX_COST_BP):
    """
    Evaluate an overnight gap trading strategy.

    Signal: if signal > 0, go long overnight (buy at prev_close, sell at day_open)
    Cost: deducted per trade (round trip)

    IMPORTANT: signal is already lagged (SPY from previous US day)
    """
    df = df.copy()
    df = df.sort_values('date').reset_index(drop=True)

    # Signal: 1 if signal_col > 0, else 0
    # signal.shift(1) is NOT needed here because the SPY signal is ALREADY
    # from a previous day (US D-1 for Taiwan D). The lag is structural.
    df['signal'] = (df[signal_col] > 0).astype(float)

    # Gross return from overnight gap when signal fires
    df['strategy_return_gross'] = df['signal'] * df['gap_return']

    # Cost: deduct cost_bp per trade (each signal=1 is a round trip)
    cost = cost_bp / 10000.0
    df['strategy_return_net'] = df['strategy_return_gross'] - df['signal'] * cost

    # Buy and hold overnight (always long)
    df['bh_return_gross'] = df['gap_return']
    df['bh_return_net'] = df['gap_return'] - cost  # always trading

    # Cumulative returns
    df['cum_strategy'] = (1 + df['strategy_return_net']).cumprod()
    df['cum_bh'] = (1 + df['bh_return_net']).cumprod()

    # Metrics
    n_days = len(df)
    n_years = n_days / 252.0

    # Strategy metrics
    avg_ret = df['strategy_return_net'].mean()
    std_ret = df['strategy_return_net'].std()
    sharpe = avg_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0

    # Drawdown
    cum = df['cum_strategy'].values
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Win rate (when signal fires)
    trades = df[df['signal'] == 1]
    n_trades = len(trades)
    win_rate = (trades['strategy_return_net'] > 0).mean() if n_trades > 0 else 0

    # Average gap (all days)
    avg_gap = df['gap_return'].mean() * 10000  # in bps

    # Conditional average gap
    avg_gap_signal_1 = df.loc[df['signal'] == 1, 'gap_return'].mean() * 10000 if n_trades > 0 else 0
    avg_gap_signal_0 = df.loc[df['signal'] == 0, 'gap_return'].mean() * 10000 if (n_days - n_trades) > 0 else 0

    # T-test for strategy return
    from scipy import stats
    if n_trades > 0 and df.loc[df['signal'] == 1, 'strategy_return_net'].std() > 0:
        t_stat, p_val = stats.ttest_1samp(df.loc[df['signal'] == 1, 'strategy_return_net'], 0)
    else:
        t_stat, p_val = 0, 1

    # Buy-and-hold metrics
    bh_avg = df['bh_return_net'].mean()
    bh_std = df['bh_return_net'].std()
    bh_sharpe = bh_avg / bh_std * np.sqrt(252) if bh_std > 0 else 0

    metrics = {
        'strategy_name': strategy_name,
        'n_days': n_days,
        'n_years': round(n_years, 2),
        'n_trades': n_trades,
        'trade_frequency': round(n_trades / n_days * 100, 1),
        'avg_gap_all_bp': round(avg_gap, 2),
        'avg_gap_signal1_bp': round(avg_gap_signal_1, 2),
        'avg_gap_signal0_bp': round(avg_gap_signal_0, 2),
        'conditional_gap_spread_bp': round(avg_gap_signal_1 - avg_gap_signal_0, 2),
        'avg_daily_return_bp': round(avg_ret * 10000, 2),
        'sharpe_ratio': round(sharpe, 3),
        'mdd': round(mdd * 100, 2),
        'win_rate': round(win_rate * 100, 1),
        't_stat': round(t_stat, 3),
        'p_value': round(p_val, 4),
        'cost_bp': cost_bp,
        'total_return_pct': round((df['cum_strategy'].iloc[-1] - 1) * 100, 2),
        'annualized_return_pct': round(((df['cum_strategy'].iloc[-1]) ** (1/n_years) - 1) * 100, 2) if n_years > 0 else 0,
        'bh_sharpe': round(bh_sharpe, 3),
        'bh_total_return_pct': round((df['cum_bh'].iloc[-1] - 1) * 100, 2),
    }

    return metrics, df


def cross_period_validation(df, signal_col, strategy_name, periods):
    """Run strategy on multiple sub-periods."""
    results = []
    for period_name, start, end in periods:
        sub = df[(df['date'] >= start) & (df['date'] <= end)].copy()
        if len(sub) < 50:
            continue
        metrics, _ = evaluate_strategy(sub, signal_col, f"{strategy_name} ({period_name})")
        metrics['period'] = period_name
        metrics['start'] = start
        metrics['end'] = end
        results.append(metrics)
    return results


# ============================================================
# STEP 5: VIX-conditioned strategies
# ============================================================

def run_vix_conditioned(merged_df):
    """Additional VIX-conditioned strategies."""
    results = {}

    # Strategy 1: SPY return > 0 (base strategy from K515)
    metrics_spy, df_spy = evaluate_strategy(merged_df, 'spy_return', 'SPY-conditioned')
    results['spy_conditioned'] = metrics_spy

    # Strategy 2: Buy-and-hold overnight (unconditional)
    df_bh = merged_df.copy()
    df_bh['always_long'] = 1.0  # Always positive signal
    metrics_bh, _ = evaluate_strategy(df_bh, 'always_long', 'Buy-Hold Overnight')
    results['buy_hold_overnight'] = metrics_bh

    # Strategy 3: SPY return > 0 AND VIX > 20 (fear + US up = mean reversion)
    df_v3 = merged_df.copy()
    df_v3['spy_up_vix_high'] = ((df_v3['spy_return'] > 0) & (df_v3['vix'] > 20)).astype(float)
    metrics_v3, _ = evaluate_strategy(df_v3, 'spy_up_vix_high', 'SPY Up + VIX>20')
    results['spy_up_vix_high'] = metrics_v3

    # Strategy 4: SPY return > 0 AND VIX <= 20 (calm + US up = momentum)
    df_v4 = merged_df.copy()
    df_v4['spy_up_vix_low'] = ((df_v4['spy_return'] > 0) & (df_v4['vix'] <= 20)).astype(float)
    metrics_v4, _ = evaluate_strategy(df_v4, 'spy_up_vix_low', 'SPY Up + VIX<=20')
    results['spy_up_vix_low'] = metrics_v4

    # Strategy 5: SPY return < 0 (contrarian — skip overnight when US falls)
    # This tests if the alpha is from going long only when SPY is up
    df_v5 = merged_df.copy()
    df_v5['spy_down'] = (df_v5['spy_return'] < 0).astype(float)
    metrics_v5, _ = evaluate_strategy(df_v5, 'spy_down', 'SPY Down (contrarian)')
    results['spy_down_contrarian'] = metrics_v5

    # Strategy 6: Large SPY move (|return| > 1%)
    df_v6 = merged_df.copy()
    df_v6['spy_big_up'] = ((df_v6['spy_return'] > 0.01)).astype(float)
    metrics_v6, _ = evaluate_strategy(df_v6, 'spy_big_up', 'SPY Big Up (>1%)')
    results['spy_big_up'] = metrics_v6

    return results, df_spy


# ============================================================
# STEP 6: Plotting
# ============================================================

def plot_results(df_strategy, merged_df, results, output_dir):
    """Generate analysis plots."""

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    # Plot 1: Cumulative returns
    ax = axes[0, 0]
    ax.plot(df_strategy['date'], df_strategy['cum_strategy'], 'b-', label='SPY-conditioned (net)', linewidth=1.5)
    ax.plot(df_strategy['date'], df_strategy['cum_bh'], 'r--', label='Buy-Hold Overnight (net)', linewidth=1.0, alpha=0.7)
    ax.set_title('Cumulative Returns: TX Overnight Gap Strategy')
    ax.set_ylabel('Cumulative Return')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # Plot 2: Gap return distribution by SPY signal
    ax = axes[0, 1]
    spy_up = merged_df[merged_df['spy_return'] > 0]['gap_return'] * 10000
    spy_down = merged_df[merged_df['spy_return'] <= 0]['gap_return'] * 10000
    ax.hist(spy_up, bins=80, alpha=0.5, label=f'SPY Up (μ={spy_up.mean():.1f}bp)', color='green', density=True)
    ax.hist(spy_down, bins=80, alpha=0.5, label=f'SPY Down (μ={spy_down.mean():.1f}bp)', color='red', density=True)
    ax.axvline(0, color='black', linestyle='-', linewidth=0.5)
    ax.set_title('Overnight Gap Distribution by SPY Signal')
    ax.set_xlabel('Gap Return (bp)')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(-200, 200)

    # Plot 3: Rolling 252-day Sharpe
    ax = axes[1, 0]
    rolling_ret = df_strategy['strategy_return_net'].rolling(252)
    rolling_sharpe = rolling_ret.mean() / rolling_ret.std() * np.sqrt(252)
    ax.plot(df_strategy['date'], rolling_sharpe, 'b-', linewidth=1.0)
    ax.axhline(0, color='red', linestyle='--', linewidth=0.5)
    ax.set_title('Rolling 1-Year Sharpe Ratio')
    ax.set_ylabel('Sharpe Ratio')
    ax.grid(True, alpha=0.3)

    # Plot 4: Strategy comparison
    ax = axes[1, 1]
    strategies = ['spy_conditioned', 'buy_hold_overnight', 'spy_up_vix_high', 'spy_up_vix_low', 'spy_down_contrarian']
    names = ['SPY Up', 'BH O/N', 'SPY Up\n+VIX>20', 'SPY Up\n+VIX≤20', 'SPY Down']
    sharpes = [results.get(s, {}).get('sharpe_ratio', 0) for s in strategies]
    colors = ['green' if s > 0 else 'red' for s in sharpes]
    ax.bar(range(len(names)), sharpes, color=colors, alpha=0.7)
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels(names, fontsize=8)
    ax.set_title('Strategy Comparison (Sharpe, net 2bp)')
    ax.set_ylabel('Sharpe Ratio')
    ax.axhline(0, color='black', linestyle='-', linewidth=0.5)
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'K1051_gap_returns.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"\nPlot saved to {output_dir}/K1051_gap_returns.png")

    # Plot 2: Gap analysis by year
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Yearly average gap by signal
    yearly = merged_df.copy()
    yearly['year'] = yearly['date'].dt.year
    yearly['spy_signal'] = (yearly['spy_return'] > 0).map({True: 'SPY Up', False: 'SPY Down'})

    yearly_stats = yearly.groupby(['year', 'spy_signal'])['gap_return'].mean().unstack() * 10000

    ax = axes[0]
    if 'SPY Up' in yearly_stats.columns:
        ax.bar(yearly_stats.index - 0.2, yearly_stats['SPY Up'], width=0.4, label='SPY Up', color='green', alpha=0.7)
    if 'SPY Down' in yearly_stats.columns:
        ax.bar(yearly_stats.index + 0.2, yearly_stats['SPY Down'], width=0.4, label='SPY Down', color='red', alpha=0.7)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_title('Average Overnight Gap by Year & SPY Signal')
    ax.set_xlabel('Year')
    ax.set_ylabel('Average Gap (bp)')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3, axis='y')

    # Monthly gap pattern
    ax = axes[1]
    monthly = merged_df.copy()
    monthly['month'] = monthly['date'].dt.month
    monthly_mean = monthly.groupby('month')['gap_return'].mean() * 10000
    colors = ['green' if x > 0 else 'red' for x in monthly_mean.values]
    ax.bar(monthly_mean.index, monthly_mean.values, color=colors, alpha=0.7)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_title('Average Overnight Gap by Month (all days)')
    ax.set_xlabel('Month')
    ax.set_ylabel('Average Gap (bp)')
    ax.set_xticks(range(1, 13))
    ax.grid(True, alpha=0.3, axis='y')

    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, 'K1051_yearly_analysis.png'), dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Plot saved to {output_dir}/K1051_yearly_analysis.png")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 70)
    print("K1051: Taiwan TX Futures Overnight Gap Strategy")
    print("=" * 70)

    # Step 1: Build daily OHLC from tick data
    cache_file = os.path.join(OUTPUT_DIR, 'K1051_daily_ohlc.csv')
    if os.path.exists(cache_file):
        print(f"\nLoading cached daily OHLC from {cache_file}")
        daily_df = pd.read_csv(cache_file, parse_dates=['date'])
    else:
        daily_df = build_daily_data()
        daily_df.to_csv(cache_file, index=False)
        print(f"Saved daily OHLC to {cache_file}")

    # Step 2: Compute overnight gaps
    gap_df = compute_overnight_gap(daily_df)

    # Descriptive statistics
    print("\n" + "=" * 50)
    print("OVERNIGHT GAP DESCRIPTIVE STATISTICS")
    print("=" * 50)
    print(f"Mean gap: {gap_df['gap_return'].mean()*10000:.2f} bp")
    print(f"Std gap: {gap_df['gap_return'].std()*10000:.2f} bp")
    print(f"Skewness: {gap_df['gap_return'].skew():.3f}")
    print(f"Kurtosis: {gap_df['gap_return'].kurtosis():.3f}")
    print(f"% positive: {(gap_df['gap_return'] > 0).mean()*100:.1f}%")
    print(f"Max gap: {gap_df['gap_return'].max()*10000:.1f} bp")
    print(f"Min gap: {gap_df['gap_return'].min()*10000:.1f} bp")

    # Step 3: Get SPY and VIX data
    spy_df = get_spy_data()
    vix_df = get_vix_data()

    # Step 4: Merge datasets
    merged_df = build_strategy_data(gap_df, spy_df, vix_df)

    # Save merged data
    merged_df.to_csv(os.path.join(OUTPUT_DIR, 'K1051_merged_data.csv'), index=False)

    # Step 5: Descriptive analysis of gap conditional on SPY
    print("\n" + "=" * 50)
    print("CONDITIONAL GAP ANALYSIS")
    print("=" * 50)
    spy_up_gaps = merged_df[merged_df['spy_return'] > 0]['gap_return']
    spy_down_gaps = merged_df[merged_df['spy_return'] <= 0]['gap_return']

    print(f"SPY Up days: n={len(spy_up_gaps)}, mean gap={spy_up_gaps.mean()*10000:.2f}bp, std={spy_up_gaps.std()*10000:.1f}bp")
    print(f"SPY Down days: n={len(spy_down_gaps)}, mean gap={spy_down_gaps.mean()*10000:.2f}bp, std={spy_down_gaps.std()*10000:.1f}bp")

    from scipy import stats
    t_diff, p_diff = stats.ttest_ind(spy_up_gaps, spy_down_gaps)
    print(f"Difference t-stat: {t_diff:.3f}, p-value: {p_diff:.4f}")

    # Step 6: Run strategies
    print("\n" + "=" * 50)
    print("STRATEGY EVALUATION (cost: 2bp)")
    print("=" * 50)

    all_results, df_strategy = run_vix_conditioned(merged_df)

    for name, metrics in all_results.items():
        print(f"\n--- {metrics['strategy_name']} ---")
        print(f"  N trades: {metrics['n_trades']}/{metrics['n_days']} ({metrics['trade_frequency']:.1f}%)")
        print(f"  Avg daily return: {metrics['avg_daily_return_bp']:.2f} bp")
        print(f"  Sharpe: {metrics['sharpe_ratio']:.3f}")
        print(f"  MDD: {metrics['mdd']:.2f}%")
        print(f"  Win rate: {metrics['win_rate']:.1f}%")
        print(f"  t-stat: {metrics['t_stat']:.3f} (p={metrics['p_value']:.4f})")
        print(f"  Total return: {metrics['total_return_pct']:.2f}%")

    # Step 7: Cross-period validation
    print("\n" + "=" * 50)
    print("CROSS-PERIOD VALIDATION")
    print("=" * 50)

    periods = [
        ("2012-2015", "2012-01-01", "2015-12-31"),
        ("2016-2019", "2016-01-01", "2019-12-31"),
        ("2020-2023", "2020-01-01", "2023-12-31"),
        ("2024-2026", "2024-01-01", "2026-12-31"),
        ("Pre-Night (2012-2017)", "2012-01-01", "2017-05-21"),
        ("Post-Night (2017-2026)", "2017-05-22", "2026-12-31"),
    ]

    cross_results = cross_period_validation(merged_df, 'spy_return', 'SPY-conditioned', periods)

    for r in cross_results:
        print(f"\n  {r['period']}: n={r['n_days']}, trades={r['n_trades']}, "
              f"Sharpe={r['sharpe_ratio']:.3f}, MDD={r['mdd']:.2f}%, "
              f"Avg gap(signal=1)={r['avg_gap_signal1_bp']:.2f}bp, t={r['t_stat']:.3f}")

    # Step 8: Sensitivity to cost
    print("\n" + "=" * 50)
    print("COST SENSITIVITY ANALYSIS")
    print("=" * 50)

    cost_results = []
    for cost in [0, 1, 2, 3, 5, 10]:
        m, _ = evaluate_strategy(merged_df, 'spy_return', f'Cost={cost}bp', cost_bp=cost)
        cost_results.append({'cost_bp': cost, 'sharpe': m['sharpe_ratio'], 'total_return': m['total_return_pct']})
        print(f"  Cost={cost}bp: Sharpe={m['sharpe_ratio']:.3f}, Total Return={m['total_return_pct']:.2f}%")

    # Step 9: Plot
    plot_results(df_strategy, merged_df, all_results, OUTPUT_DIR)

    # Step 10: Save results
    results_output = {
        'experiment_id': 'K1051',
        'title': 'TX Futures Overnight Gap Strategy (SPY-conditioned)',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX tick data (2012-2026) + yfinance (SPY/VIX)',
        'sample_period': f"{merged_df['date'].min().strftime('%Y-%m-%d')} to {merged_df['date'].max().strftime('%Y-%m-%d')}",
        'n_observations': len(merged_df),
        'tx_cost_bp': TX_COST_BP,
        'descriptive_stats': {
            'mean_gap_bp': round(gap_df['gap_return'].mean() * 10000, 2),
            'std_gap_bp': round(gap_df['gap_return'].std() * 10000, 2),
            'skewness': round(gap_df['gap_return'].skew(), 3),
            'kurtosis': round(gap_df['gap_return'].kurtosis(), 3),
            'pct_positive': round((gap_df['gap_return'] > 0).mean() * 100, 1),
            'conditional_spy_up_mean_bp': round(spy_up_gaps.mean() * 10000, 2),
            'conditional_spy_down_mean_bp': round(spy_down_gaps.mean() * 10000, 2),
            'conditional_diff_t_stat': round(t_diff, 3),
            'conditional_diff_p_value': round(p_diff, 4),
        },
        'strategies': all_results,
        'cross_period_validation': cross_results,
        'cost_sensitivity': cost_results,
        'key_findings': [],
        'references': [
            'K515: Overnight gap alpha (SPY-conditioned 10.73bp/day, t=4.06)',
            'K515: ETF TX cost 18.55bp killed profitability',
        ]
    }

    # Generate key findings
    spy_metrics = all_results.get('spy_conditioned', {})
    if spy_metrics.get('sharpe_ratio', 0) > 0.5:
        results_output['key_findings'].append(
            f"SPY-conditioned overnight gap strategy achieves Sharpe {spy_metrics['sharpe_ratio']:.3f} "
            f"net of {TX_COST_BP}bp TX cost — PROFITABLE with futures"
        )
    elif spy_metrics.get('t_stat', 0) > 2.0:
        results_output['key_findings'].append(
            f"SPY-conditioned gap alpha is statistically significant (t={spy_metrics['t_stat']:.3f}) "
            f"but Sharpe {spy_metrics['sharpe_ratio']:.3f} is modest after costs"
        )
    else:
        results_output['key_findings'].append(
            f"SPY-conditioned gap strategy Sharpe={spy_metrics['sharpe_ratio']:.3f}, "
            f"t={spy_metrics['t_stat']:.3f} — alpha weak even with low TX costs"
        )

    # Check if night session era differs
    pre_night = [r for r in cross_results if 'Pre-Night' in r.get('period', '')]
    post_night = [r for r in cross_results if 'Post-Night' in r.get('period', '')]
    if pre_night and post_night:
        results_output['key_findings'].append(
            f"Pre-night session Sharpe={pre_night[0]['sharpe_ratio']:.3f} vs "
            f"Post-night session Sharpe={post_night[0]['sharpe_ratio']:.3f}"
        )

    # Save JSON
    json_path = os.path.join(OUTPUT_DIR, 'K1051_results.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(results_output, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {json_path}")

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for finding in results_output['key_findings']:
        print(f"  • {finding}")
    print("=" * 70)

    return results_output


if __name__ == '__main__':
    results = main()
