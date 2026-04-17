#!/usr/bin/env python3
"""
K843: TAIFEX Night Session Intraday Strategies
================================================
Core Concept: TX futures price IS the real-time signal.
After US open, TX reacts immediately — no external VIX needed.

Strategies use only night-session tick data for signals:
- S0: Buy-and-hold night session (benchmark)
- S1: Slot C (21:30-00:00) momentum → hold/short to 05:00
- S2: US open reaction (21:00-22:00 TX move) → position to 05:00
- S3: Night session VWAP crossover
- S4: Slot A→C regime alignment

Data: TAIFEX TX tick data, 2017-05-16 onwards (after night session introduced)
Transaction cost: 2 ticks round-trip ≈ 0.01% (conservative for TX)

Error log rules applied:
- Filter to max-volume expiry month only
- Volume: int(float()) for decimal handling
- Time codes: 6-digit HHMMSS (213000 = 21:30:00)
- Skip days without post-21:30 data (US holidays)
"""

import os
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, date
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import defaultdict

warnings.filterwarnings('ignore')

DATA_DIR = '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python'
MIN_FILE_SIZE = 100  # bytes
TX_COST = 0.0001  # 2 ticks round-trip ≈ 0.01%

# Time slot boundaries (HHMMSS format)
SLOT_A_START = 150000  # 15:00
SLOT_A_END   = 170000  # 17:00
SLOT_B_START = 170000
SLOT_B_END   = 213000  # 21:30
SLOT_C_START = 213000
SLOT_C_END   = 240000  # 24:00 → represented as next day 000000
SLOT_D_START = 0       # 00:00 (next calendar day)
SLOT_D_END   = 40000   # 04:00
SLOT_E_START = 40000
SLOT_E_END   = 50000   # 05:00
DAY_START    = 84500   # 08:45
DAY_END      = 134500  # 13:45


def safe_volume(v):
    """Handle volume that might be float string."""
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return 0


def parse_tx_file(filepath):
    """
    Parse a single TX CSV file.
    Returns dict with slot-level OHLCV for the max-volume expiry month.

    File structure:
    - Date1 (prev calendar day): night session 15:00-23:59
    - Date2 (current calendar day): night session 00:00-05:00 + day session 08:45-13:45
    """
    try:
        if os.path.getsize(filepath) < MIN_FILE_SIZE:
            return None

        df = pd.read_csv(filepath, encoding='big5')
        if len(df) < 10:
            return None

        # Rename columns for convenience
        df.columns = ['date', 'product', 'expiry', 'time', 'price', 'volume',
                       'near_price', 'far_price', 'open_auction', 'timestamp']

        # Filter TX only
        df = df[df['product'].str.strip() == 'TX'].copy()
        if len(df) < 10:
            return None

        # Convert types
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['volume'] = df['volume'].apply(safe_volume)
        df['time'] = pd.to_numeric(df['time'], errors='coerce').fillna(0).astype(int)
        df['date'] = pd.to_numeric(df['date'], errors='coerce').fillna(0).astype(int)
        df = df.dropna(subset=['price'])

        if len(df) < 10:
            return None

        # Get unique dates
        dates = sorted(df['date'].unique())

        # Identify night session dates vs day session date
        # Night session: the earlier date has times >= 150000
        # The later date has times < 50000 (early morning) AND times >= 84500 (day session)
        if len(dates) < 2:
            return None

        night_date_1 = dates[0]  # evening part (15:00-23:59)
        day_date = dates[-1]     # morning part (00:00-05:00) + day session

        # Filter to max-volume expiry for night session
        night_evening = df[(df['date'] == night_date_1) & (df['time'] >= 150000)]
        night_morning = df[(df['date'] == day_date) & (df['time'] < 50000)]

        night_all = pd.concat([night_evening, night_morning])

        if len(night_all) < 5:
            return None

        # Find max-volume expiry
        vol_by_expiry = night_all.groupby('expiry')['volume'].sum()
        if len(vol_by_expiry) == 0:
            return None
        max_expiry = vol_by_expiry.idxmax()

        # Filter to max expiry for ALL data
        night_all = night_all[night_all['expiry'] == max_expiry].copy()

        # Also get day session with same expiry
        day_session = df[(df['date'] == day_date) &
                         (df['time'] >= DAY_START) & (df['time'] <= DAY_END) &
                         (df['expiry'] == max_expiry)].copy()

        if len(night_all) < 5:
            return None

        # Build result
        result = {
            'file': os.path.basename(filepath),
            'night_date': int(night_date_1),
            'day_date': int(day_date),
            'expiry': int(max_expiry),
            'night_ticks': len(night_all),
        }

        # Helper to compute OHLCV for a subset
        def ohlcv(sub):
            if len(sub) == 0:
                return None
            return {
                'open': float(sub.iloc[0]['price']),
                'high': float(sub['price'].max()),
                'low': float(sub['price'].min()),
                'close': float(sub.iloc[-1]['price']),
                'volume': int(sub['volume'].sum()),
                'n_ticks': len(sub),
            }

        # Slot A: 15:00-17:00 (evening date)
        slot_a = night_evening[(night_evening['time'] >= SLOT_A_START) &
                               (night_evening['time'] < SLOT_A_END) &
                               (night_evening['expiry'] == max_expiry)]
        result['slot_a'] = ohlcv(slot_a)

        # Slot B: 17:00-21:30
        slot_b = night_evening[(night_evening['time'] >= SLOT_B_START) &
                               (night_evening['time'] < SLOT_B_END) &
                               (night_evening['expiry'] == max_expiry)]
        result['slot_b'] = ohlcv(slot_b)

        # Slot C: 21:30-24:00 (from evening date)
        slot_c = night_evening[(night_evening['time'] >= SLOT_C_START) &
                               (night_evening['expiry'] == max_expiry)]
        result['slot_c'] = ohlcv(slot_c)

        # Slot D: 00:00-04:00 (morning date)
        slot_d = night_morning[(night_morning['time'] >= SLOT_D_START) &
                               (night_morning['time'] < SLOT_D_END) &
                               (night_morning['expiry'] == max_expiry)]
        result['slot_d'] = ohlcv(slot_d)

        # Slot E: 04:00-05:00 (morning date)
        slot_e = night_morning[(night_morning['time'] >= SLOT_E_START) &
                               (night_morning['time'] < SLOT_E_END) &
                               (night_morning['expiry'] == max_expiry)]
        result['slot_e'] = ohlcv(slot_e)

        # Night session full: open of slot A to close of last available slot
        result['night_full'] = ohlcv(night_all)

        # Day session
        result['day_session'] = ohlcv(day_session)

        # US open reaction window: 21:00-22:00
        us_open_window = night_evening[
            (night_evening['time'] >= 210000) &
            (night_evening['time'] < 220000) &
            (night_evening['expiry'] == max_expiry)
        ]
        result['us_open_window'] = ohlcv(us_open_window)

        # For VWAP strategy, store all night session ticks with price & volume
        # (only store aggregated 5-min bars to save memory)
        night_sorted = night_all.sort_values('time' if len(night_evening) > 0 else 'time')
        # Create a continuous time index
        # Evening: 150000-235959 → keep as is
        # Morning: 000000-050000 → add 240000 to make continuous
        times = night_all['time'].values.copy()
        is_morning = night_all['date'].values == day_date
        times[is_morning] = times[is_morning] + 240000
        night_all_sorted = night_all.copy()
        night_all_sorted['cont_time'] = times
        night_all_sorted = night_all_sorted.sort_values('cont_time')

        # 5-min bars for VWAP
        night_all_sorted['bar'] = (night_all_sorted['cont_time'] // 500) * 500  # ~5 min groups
        bars_5min = night_all_sorted.groupby('bar').agg(
            open=('price', 'first'),
            high=('price', 'max'),
            low=('price', 'min'),
            close=('price', 'last'),
            volume=('volume', 'sum'),
            n_ticks=('price', 'count'),
        ).reset_index()

        result['bars_5min'] = bars_5min.to_dict('records')

        # Night close to next morning (for overnight gap)
        # The last price in night session
        last_night_price = float(night_all_sorted.iloc[-1]['price'])
        result['night_close_price'] = last_night_price

        # First price in day session
        if len(day_session) > 0:
            result['day_open_price'] = float(day_session.iloc[0]['price'])
            result['day_close_price'] = float(day_session.iloc[-1]['price'])

        return result

    except Exception as e:
        return None


def compute_strategies(daily_data):
    """
    Compute strategy signals and returns from daily slot data.
    All strategies use night-session data as signals.
    """
    results = []

    for i, day in enumerate(daily_data):
        rec = {
            'night_date': day['night_date'],
            'day_date': day['day_date'],
        }

        # === S0: Buy-and-hold night session ===
        nf = day.get('night_full')
        if nf and nf['open'] > 0:
            night_ret = (nf['close'] - nf['open']) / nf['open']
            rec['s0_ret'] = night_ret - TX_COST  # one round-trip

        # === Night session close price (for slot returns) ===
        slot_a = day.get('slot_a')
        slot_b = day.get('slot_b')
        slot_c = day.get('slot_c')
        slot_d = day.get('slot_d')
        slot_e = day.get('slot_e')

        # Slot returns
        if slot_a and slot_a['open'] > 0:
            rec['slot_a_ret'] = (slot_a['close'] - slot_a['open']) / slot_a['open']
        if slot_c and slot_c['open'] > 0:
            rec['slot_c_ret'] = (slot_c['close'] - slot_c['open']) / slot_c['open']

        # Day session return (next day performance)
        ds = day.get('day_session')
        if ds and ds['open'] > 0:
            rec['day_ret'] = (ds['close'] - ds['open']) / ds['open']

        # Overnight gap
        if day.get('night_close_price') and day.get('day_open_price'):
            rec['overnight_gap'] = (day['day_open_price'] - day['night_close_price']) / day['night_close_price']

        # === S1: Slot C Momentum ===
        # After US open (21:30), observe TX until 00:00
        # If Slot C return > +0.3%: long to 05:00
        # If Slot C return < -0.3%: short to 05:00
        # Else: no trade
        if slot_c and slot_c['open'] > 0:
            c_ret = (slot_c['close'] - slot_c['open']) / slot_c['open']

            # Entry at slot C close, exit at night session end
            # Need to compute return from slot C close to night session end
            # This is slots D + E combined
            entry_price = slot_c['close']

            # Find exit price (end of night session)
            if slot_e and slot_e['close'] > 0:
                exit_price = slot_e['close']
            elif slot_d and slot_d['close'] > 0:
                exit_price = slot_d['close']
            else:
                exit_price = None

            if exit_price and entry_price > 0:
                remaining_ret = (exit_price - entry_price) / entry_price

                if c_ret > 0.003:  # > +0.3%
                    rec['s1_signal'] = 1
                    rec['s1_ret'] = remaining_ret - TX_COST
                elif c_ret < -0.003:  # < -0.3%
                    rec['s1_signal'] = -1
                    rec['s1_ret'] = -remaining_ret - TX_COST
                else:
                    rec['s1_signal'] = 0
                    rec['s1_ret'] = 0.0  # no trade, no cost

        # === S2: US Open Reaction ===
        # TX price change around 21:00-22:00
        us_win = day.get('us_open_window')
        if us_win and us_win['open'] > 0 and us_win['n_ticks'] >= 3:
            us_ret = (us_win['close'] - us_win['open']) / us_win['open']

            # Entry at 22:00 (us_open_window close), exit at night session end
            entry_price = us_win['close']

            if slot_e and slot_e['close'] > 0:
                exit_price = slot_e['close']
            elif slot_d and slot_d['close'] > 0:
                exit_price = slot_d['close']
            elif slot_c and slot_c['close'] > 0:
                exit_price = slot_c['close']
            else:
                exit_price = None

            if exit_price and entry_price > 0:
                remaining_ret = (exit_price - entry_price) / entry_price

                if us_ret > 0.005:  # > +0.5%
                    rec['s2_signal'] = 1
                    rec['s2_ret'] = remaining_ret - TX_COST
                elif us_ret < -0.005:  # < -0.5%
                    rec['s2_signal'] = -1
                    rec['s2_ret'] = -remaining_ret - TX_COST
                else:
                    rec['s2_signal'] = 0
                    rec['s2_ret'] = 0.0

        # === S3: VWAP Crossover (Real-time implementable) ===
        # At each bar, compute running VWAP (only past data).
        # When price crosses VWAP, flip position.
        # Track ALL trades (crossover→crossover or crossover→session end).
        # Total return = sum of all trade segments minus TX_COST per flip.
        bars = day.get('bars_5min', [])
        if len(bars) >= 10:
            cum_pv = 0.0
            cum_vol = 0
            prev_pos = 0  # no position initially
            entry_price = None
            total_s3_ret = 0.0
            n_flips = 0

            for bar_idx, bar in enumerate(bars):
                cum_pv += bar['close'] * bar['volume']
                cum_vol += bar['volume']
                if cum_vol <= 0:
                    continue
                vwap = cum_pv / cum_vol
                # Current position signal
                cur_pos = 1 if bar['close'] > vwap else -1

                if prev_pos == 0:
                    # First bar: take initial position
                    prev_pos = cur_pos
                    entry_price = bar['close']
                elif cur_pos != prev_pos:
                    # Crossover: close old position, open new one
                    if entry_price and entry_price > 0:
                        seg_ret = (bar['close'] - entry_price) / entry_price
                        if prev_pos == -1:
                            seg_ret = -seg_ret  # was short
                        total_s3_ret += seg_ret - TX_COST  # cost per flip
                        n_flips += 1
                    prev_pos = cur_pos
                    entry_price = bar['close']

            # Close final position at session end
            if prev_pos != 0 and entry_price and entry_price > 0 and len(bars) > 0:
                final_price = bars[-1]['close']
                seg_ret = (final_price - entry_price) / entry_price
                if prev_pos == -1:
                    seg_ret = -seg_ret
                total_s3_ret += seg_ret - TX_COST  # closing cost

            rec['s3_signal'] = prev_pos
            rec['s3_ret'] = total_s3_ret
            rec['s3_n_crossovers'] = n_flips

        # === S4: Slot A→C Regime Alignment ===
        # If A and C same direction: strong signal → trade D+E
        # If opposite: no trade
        if slot_a and slot_a['open'] > 0 and slot_c and slot_c['open'] > 0:
            a_ret = (slot_a['close'] - slot_a['open']) / slot_a['open']
            c_ret = (slot_c['close'] - slot_c['open']) / slot_c['open']

            a_dir = 1 if a_ret > 0.001 else (-1 if a_ret < -0.001 else 0)
            c_dir = 1 if c_ret > 0.001 else (-1 if c_ret < -0.001 else 0)

            # Entry at slot C close, exit at night session end
            entry_price = slot_c['close']
            if slot_e and slot_e['close'] > 0:
                exit_price = slot_e['close']
            elif slot_d and slot_d['close'] > 0:
                exit_price = slot_d['close']
            else:
                exit_price = None

            if exit_price and entry_price > 0:
                remaining_ret = (exit_price - entry_price) / entry_price

                if a_dir != 0 and c_dir != 0 and a_dir == c_dir:
                    # Aligned: strong signal
                    rec['s4_signal'] = c_dir
                    rec['s4_ret'] = (remaining_ret if c_dir == 1 else -remaining_ret) - TX_COST
                else:
                    rec['s4_signal'] = 0
                    rec['s4_ret'] = 0.0

        results.append(rec)

    return results


def evaluate_strategy(returns, name):
    """Compute strategy metrics from returns series."""
    rets = np.array(returns)
    rets = rets[~np.isnan(rets)]

    if len(rets) == 0:
        return {'name': name, 'error': 'no trades'}

    n_trades = np.sum(rets != 0)
    total_trades = len(rets)

    # Only non-zero trades for win rate
    active_rets = rets[rets != 0]

    mean_ret = np.mean(rets) if len(rets) > 0 else 0
    std_ret = np.std(rets, ddof=1) if len(rets) > 1 else 1e-10

    # Annualized (252 trading days)
    ann_ret = mean_ret * 252
    ann_vol = std_ret * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Win rate (among actual trades)
    win_rate = np.mean(active_rets > 0) if len(active_rets) > 0 else 0

    # Max drawdown
    cum = np.cumsum(rets)
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    mdd = np.min(dd) if len(dd) > 0 else 0

    # Profit factor
    gains = active_rets[active_rets > 0]
    losses = active_rets[active_rets < 0]
    pf = np.sum(gains) / abs(np.sum(losses)) if len(losses) > 0 and np.sum(losses) != 0 else np.inf

    return {
        'name': name,
        'n_days': total_trades,
        'n_active_trades': int(n_trades),
        'trade_pct': round(n_trades / total_trades * 100, 1) if total_trades > 0 else 0,
        'mean_daily_ret_bps': round(mean_ret * 10000, 2),
        'ann_return_pct': round(ann_ret * 100, 2),
        'ann_vol_pct': round(ann_vol * 100, 2),
        'sharpe': round(sharpe, 3),
        'win_rate_pct': round(win_rate * 100, 1),
        'max_drawdown_pct': round(mdd * 100, 2),
        'profit_factor': round(pf, 2) if pf != np.inf else 'inf',
        'total_return_pct': round(np.sum(rets) * 100, 2),
        'avg_win_bps': round(np.mean(gains) * 10000, 2) if len(gains) > 0 else 0,
        'avg_loss_bps': round(np.mean(losses) * 10000, 2) if len(losses) > 0 else 0,
    }


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided)."""
    d = np.array(e1) - np.array(e2)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return {'stat': 0, 'p_value': 1.0}

    d_mean = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    total_var = gamma_0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_mean) * (d[:-k] - d_mean)) / n
        total_var += 2 * gamma_k

    se = np.sqrt(total_var / n) if total_var > 0 else 1e-10
    stat = d_mean / se

    from scipy.stats import t as t_dist
    p_value = 2 * (1 - t_dist.cdf(abs(stat), df=n-1))

    return {'stat': round(stat, 3), 'p_value': round(p_value, 4)}


def yearly_breakdown(df_results, col):
    """Compute yearly Sharpe ratios."""
    yearly = {}
    for _, row in df_results.iterrows():
        year = int(str(int(row['day_date']))[:4])
        if year not in yearly:
            yearly[year] = []
        if pd.notna(row.get(col)):
            yearly[year].append(row[col])

    result = {}
    for year in sorted(yearly.keys()):
        rets = np.array(yearly[year])
        if len(rets) >= 20:
            m = np.mean(rets)
            s = np.std(rets, ddof=1)
            sh = (m * 252) / (s * np.sqrt(252)) if s > 0 else 0
            wr = np.mean(rets[rets != 0] > 0) * 100 if np.sum(rets != 0) > 0 else 0
            result[year] = {
                'sharpe': round(sh, 3),
                'win_rate': round(wr, 1),
                'n_days': len(rets),
                'mean_ret_bps': round(m * 10000, 2),
            }
    return result


def main():
    t0 = time.time()
    print("=" * 70)
    print("K843: TAIFEX Night Session Intraday Strategies")
    print("=" * 70)

    # Step 1: Find all TX files from 2017-05-16 onwards
    all_files = sorted([
        os.path.join(DATA_DIR, f)
        for f in os.listdir(DATA_DIR)
        if f.startswith('Daily_') and f.endswith('TX.csv')
        and f >= 'Daily_2017_05_16'
    ])

    # Filter by file size
    valid_files = [f for f in all_files if os.path.getsize(f) > MIN_FILE_SIZE]
    print(f"\nFound {len(valid_files)} TX files from 2017-05-16 onwards")

    # Step 2: Parse all files in parallel
    print("\nParsing TX tick data (parallel)...")
    daily_data = []
    n_failed = 0

    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(parse_tx_file, f): f for f in valid_files}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                daily_data.append(result)
            else:
                n_failed += 1

    # Sort by night_date
    daily_data.sort(key=lambda x: x['night_date'])

    t_parse = time.time()
    print(f"Parsed {len(daily_data)} valid trading days ({n_failed} failed)")
    print(f"Date range: {daily_data[0]['night_date']} - {daily_data[-1]['night_date']}")
    print(f"Parse time: {t_parse - t0:.1f}s")

    # Step 3: Compute strategies
    print("\nComputing strategies...")
    strategy_results = compute_strategies(daily_data)
    df = pd.DataFrame(strategy_results)

    print(f"Total trading days with results: {len(df)}")

    # Step 4: Correlations
    print("\n" + "=" * 70)
    print("SLOT RETURN CORRELATIONS")
    print("=" * 70)

    # Slot C return vs next day session return
    mask = df['slot_c_ret'].notna() & df['day_ret'].notna()
    if mask.sum() > 20:
        corr_c_day = df.loc[mask, 'slot_c_ret'].corr(df.loc[mask, 'day_ret'])
        print(f"\nSlot C return → Next-day return: r = {corr_c_day:.4f} (n={mask.sum()})")

    # Slot A → Slot C
    mask2 = df['slot_a_ret'].notna() & df['slot_c_ret'].notna()
    if mask2.sum() > 20:
        corr_a_c = df.loc[mask2, 'slot_a_ret'].corr(df.loc[mask2, 'slot_c_ret'])
        print(f"Slot A return → Slot C return:   r = {corr_a_c:.4f} (n={mask2.sum()})")

    # Slot C → overnight gap
    mask3 = df['slot_c_ret'].notna() & df['overnight_gap'].notna()
    if mask3.sum() > 20:
        corr_c_gap = df.loc[mask3, 'slot_c_ret'].corr(df.loc[mask3, 'overnight_gap'])
        print(f"Slot C return → Overnight gap:   r = {corr_c_gap:.4f} (n={mask3.sum()})")

    # Night full return → next day return
    mask4 = df['s0_ret'].notna() & df['day_ret'].notna()
    if mask4.sum() > 20:
        corr_night_day = df.loc[mask4, 's0_ret'].corr(df.loc[mask4, 'day_ret'])
        print(f"Night full ret → Next-day ret:   r = {corr_night_day:.4f} (n={mask4.sum()})")

    # Step 5: Strategy evaluation
    print("\n" + "=" * 70)
    print("STRATEGY PERFORMANCE")
    print("=" * 70)

    strategies = {
        'S0: BH Night Session': 's0_ret',
        'S1: Slot C Momentum': 's1_ret',
        'S2: US Open Reaction': 's2_ret',
        'S3: VWAP Crossover': 's3_ret',
        'S4: Slot A→C Alignment': 's4_ret',
    }

    all_metrics = {}
    for name, col in strategies.items():
        if col in df.columns:
            rets = df[col].dropna().values
            metrics = evaluate_strategy(rets, name)
            all_metrics[name] = metrics

            print(f"\n{name}:")
            print(f"  Days: {metrics['n_days']}, Active Trades: {metrics['n_active_trades']} ({metrics['trade_pct']}%)")
            print(f"  Ann. Return: {metrics['ann_return_pct']}%, Ann. Vol: {metrics['ann_vol_pct']}%")
            print(f"  Sharpe: {metrics['sharpe']}")
            print(f"  Win Rate: {metrics['win_rate_pct']}%")
            print(f"  Max DD: {metrics['max_drawdown_pct']}%")
            print(f"  Profit Factor: {metrics['profit_factor']}")
            print(f"  Avg Win: {metrics['avg_win_bps']} bps, Avg Loss: {metrics['avg_loss_bps']} bps")
            print(f"  Total Return: {metrics['total_return_pct']}%")

    # Step 6: DM tests vs S0
    print("\n" + "=" * 70)
    print("DM TESTS vs S0 (Buy-and-Hold Night)")
    print("=" * 70)

    dm_results = {}
    s0_rets = df['s0_ret'].dropna()

    for name, col in strategies.items():
        if col == 's0_ret' or col not in df.columns:
            continue
        # Align on common days
        common = df[['s0_ret', col]].dropna()
        if len(common) > 20:
            # Use squared errors (loss function: return magnitude)
            e1 = -common['s0_ret'].values  # negative for loss (we want positive returns)
            e2 = -common[col].values
            dm = dm_test(e1**2, e2**2)
            dm_results[name] = dm
            sig = "***" if abs(dm['stat']) > 3.0 else ("**" if abs(dm['stat']) > 2.0 else ("*" if abs(dm['stat']) > 1.65 else ""))
            print(f"  {name}: DM stat = {dm['stat']}, p = {dm['p_value']} {sig}")

    # Step 7: Yearly breakdown
    print("\n" + "=" * 70)
    print("YEARLY SHARPE RATIOS")
    print("=" * 70)

    yearly_data = {}
    for name, col in strategies.items():
        if col in df.columns:
            yb = yearly_breakdown(df, col)
            yearly_data[name] = yb

    # Print table
    years = sorted(set(y for yb in yearly_data.values() for y in yb.keys()))
    header = f"{'Year':<8}" + "".join(f"{name[:20]:<22}" for name in strategies.keys())
    print(header)
    print("-" * len(header))

    for year in years:
        row = f"{year:<8}"
        for name in strategies.keys():
            if year in yearly_data.get(name, {}):
                sh = yearly_data[name][year]['sharpe']
                wr = yearly_data[name][year]['win_rate']
                row += f"{sh:>7.2f} ({wr:.0f}%)        "
            else:
                row += f"{'N/A':>22}"
        print(row)

    # Step 8: Slot C statistics
    print("\n" + "=" * 70)
    print("SLOT C RETURN DISTRIBUTION")
    print("=" * 70)

    c_rets = df['slot_c_ret'].dropna()
    if len(c_rets) > 0:
        print(f"  N = {len(c_rets)}")
        print(f"  Mean: {c_rets.mean()*10000:.2f} bps")
        print(f"  Std:  {c_rets.std()*10000:.2f} bps")
        print(f"  Skew: {c_rets.skew():.3f}")
        print(f"  Kurt: {c_rets.kurtosis():.3f}")
        print(f"  |ret| > 0.3%: {(abs(c_rets) > 0.003).sum()} days ({(abs(c_rets) > 0.003).mean()*100:.1f}%)")
        print(f"  |ret| > 0.5%: {(abs(c_rets) > 0.005).sum()} days ({(abs(c_rets) > 0.005).mean()*100:.1f}%)")
        print(f"  |ret| > 1.0%: {(abs(c_rets) > 0.01).sum()} days ({(abs(c_rets) > 0.01).mean()*100:.1f}%)")

    # Step 9: Save results
    t_end = time.time()

    output = {
        'experiment_id': 'K843',
        'title': 'TAIFEX Night Session Intraday Strategies Using TX Tick Data',
        'description': 'TX futures price as real-time signal. Night session slot-based strategies.',
        'data_source': 'TAIFEX TX tick data (Daily_*TX.csv)',
        'data_period': f"{daily_data[0]['night_date']} - {daily_data[-1]['night_date']}",
        'n_trading_days': len(daily_data),
        'runtime_seconds': round(t_end - t0, 1),
        'tx_cost_assumption': '2 ticks round-trip (0.01%)',
        'correlations': {
            'slot_c_vs_next_day': round(corr_c_day, 4) if 'corr_c_day' in dir() else None,
            'slot_a_vs_slot_c': round(corr_a_c, 4) if 'corr_a_c' in dir() else None,
            'slot_c_vs_overnight_gap': round(corr_c_gap, 4) if 'corr_c_gap' in dir() else None,
            'night_full_vs_next_day': round(corr_night_day, 4) if 'corr_night_day' in dir() else None,
        },
        'strategy_metrics': all_metrics,
        'dm_tests_vs_s0': dm_results,
        'yearly_sharpe': yearly_data,
        'slot_c_stats': {
            'n': int(len(c_rets)),
            'mean_bps': round(c_rets.mean() * 10000, 2),
            'std_bps': round(c_rets.std() * 10000, 2),
            'skew': round(c_rets.skew(), 3),
            'kurtosis': round(c_rets.kurtosis(), 3),
            'pct_above_30bps': round((abs(c_rets) > 0.003).mean() * 100, 1),
        } if len(c_rets) > 0 else None,
        'conclusion': '',  # will be filled below
    }

    # Build conclusion
    best_strat = max(all_metrics.items(), key=lambda x: x[1].get('sharpe', -999))
    conclusions = []
    conclusions.append(f"Best strategy: {best_strat[0]} (Sharpe {best_strat[1]['sharpe']})")

    s0_sharpe = all_metrics.get('S0: BH Night Session', {}).get('sharpe', 0)
    conclusions.append(f"BH Night benchmark: Sharpe {s0_sharpe}")

    if 'corr_c_day' in dir():
        conclusions.append(f"Slot C → next-day correlation: {corr_c_day:.4f}")

    output['conclusion'] = '; '.join(conclusions)

    # Save
    out_path = os.path.join(os.path.dirname(__file__), 'k843_intraday_futures_results.json')

    # Make yearly_sharpe JSON-serializable (convert int keys)
    serializable_yearly = {}
    for name, yb in yearly_data.items():
        serializable_yearly[name] = {str(k): v for k, v in yb.items()}
    output['yearly_sharpe'] = serializable_yearly

    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\nResults saved to {out_path}")
    print(f"Total runtime: {t_end - t0:.1f}s")

    return output


if __name__ == '__main__':
    main()
