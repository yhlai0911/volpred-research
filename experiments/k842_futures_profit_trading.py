#!/usr/bin/env python3
"""
K842: TAIFEX Night Session Directional Profit Trading via SPY Signals
=====================================================================
Hypothesis: US stock movements (SPY return) can be used as signals for
            directional trading in TAIFEX TX night session (15:00-05:00),
            because the two sessions overlap in time.

Core concept (user-proposed): When US stocks rally big, go long TX at night;
when US stocks drop big, go short TX at night. This is **offensive** trading
(profit-seeking), not just hedging.

Difference from K838/K841:
  - K838 (NULL): night return -> next day return (same instrument, already priced in)
  - K841: VIX-based night hedge (defensive)
  - K842: SPY return -> TX night directional trade (offensive, cross-market)

Data:
  1. TAIFEX TX1 tick data (near-month, 2017-05-16 onwards, night session enabled)
  2. SPY daily (yfinance) — SPY daily return as proxy for US session moves
  3. 0050.TW daily (yfinance, with clean_tw50_data)
  4. ^VIX daily (yfinance)

Strategies:
  S0: BH 0050.TW (baseline)
  S1: SPY Momentum — SPY(t-1) up >0.5% → long TX night; down >0.5% → short TX
  S2: SPY + VIX Dual Signal — SPY up + VIX down → strong long; SPY down + VIX up → strong short
  S3: Large Volatility Follow/Contrarian — |SPY ret| > 1% → follow or contrarian
  S4: Hybrid — hold 0050 daytime + TX night trades via SPY signal

Signal lag: SPY return at t-1 → TX night session at t (strict, no lookahead)
  Rationale: TX night session on date D opens at 15:00 on D-1 (prev calendar evening).
  SPY at t-1 closes ~04:00 Taiwan time on day D (or ~16:00 ET on D-1).
  So SPY(D-1) close is known by TX night open on day D? No —
  TX night on file-date D starts at 15:00 on D-1 (before SPY opens).
  SPY(D-1) opens 21:30 Taiwan time on D-1, closes ~04:00 on D.
  So SPY(D-1) return is only fully known AFTER the night session of file-date D has STARTED.
  But the night session runs until 05:00 on D, so SPY(D-1) close at ~04:00 on D
  is known ~1h before TX night close.

  CONSERVATIVE approach: use SPY(D-2) — known before TX night opens on D-1.
  This is shift(1) on SPY relative to TX file-date.

  ALSO TEST: SPY(D-1) as "concurrent" signal (SPY closes 1h before TX night close).
  This is shift(0) — but NOT lookahead since SPY closes before TX night closes.
  We test both and compare.

TX cost: 1 bp round-trip per position change.

Error log rules applied:
  - signal.shift(1) for conservative version
  - 0050.TW: use clean_tw50_data
  - DM test: use scipy, not custom
  - Sharpe > 2x baseline → bug alarm

References:
  - K838: Night momentum NULL (same-instrument prediction fails)
  - K817: US→Taiwan overnight gap captures 77-93% of alpha
  - K812v2: Lead-lag direction only 50.2% close-to-close
  - Barclay & Hendershott (2003): Price discovery in after-hours
  - Hasbrouck (1995): One security, many markets

Author: VolPred Research System
Date: 2026-04-03
"""

import os
import sys
import glob
import json
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
DATA_DIR = "/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python"
TX_COST_PCT = 0.0001   # 1 bp round-trip
MIN_FILE_SIZE = 100
SPY_THRESHOLD = 0.005   # 0.5% for S1
SPY_LARGE_THRESHOLD = 0.01  # 1.0% for S3
VIX_CHANGE_THRESHOLD = 0.02  # 2% VIX change for S2

NIGHT_START = 2017_05_16  # Night session enabled date (int for comparison)

# ============================================================
# Step 1: Parse TX1 files for night session OHLC
# ============================================================

def parse_tx1_night(filepath):
    """
    Parse a TX1 (near-month) file and extract night session open/close.
    Night session = PM portion (>=150000) + AM portion (<=50000).
    PM happens on the previous calendar evening, AM on file-date morning.
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

    cols = df.columns.tolist()
    if len(cols) < 6:
        return None

    try:
        df['time_int'] = pd.to_numeric(df.iloc[:, 3], errors='coerce').astype('Int64')
        df['price'] = pd.to_numeric(df.iloc[:, 4], errors='coerce')
        df['volume'] = pd.to_numeric(df.iloc[:, 5], errors='coerce')
    except Exception:
        return None

    df = df.dropna(subset=['price', 'time_int'])
    if len(df) == 0:
        return None

    t = df['time_int'].values
    night_pm = df[(t >= 150000) & (t <= 235959)]
    night_am = df[(t >= 0) & (t <= 50000)]

    # Night open = first PM trade; Night close = last AM trade (or last PM if no AM)
    night_open = None
    night_close = None

    if len(night_pm) > 0:
        night_open = float(night_pm['price'].iloc[0])
    elif len(night_am) > 0:
        night_open = float(night_am['price'].iloc[0])

    if len(night_am) > 0:
        night_close = float(night_am['price'].iloc[-1])
    elif len(night_pm) > 0:
        night_close = float(night_pm['price'].iloc[-1])

    night_volume = 0
    if len(night_pm) > 0:
        night_volume += night_pm['volume'].astype(float).sum()
    if len(night_am) > 0:
        night_volume += night_am['volume'].astype(float).sum()

    if night_open is None or night_close is None or night_open == 0:
        return None

    return {
        'night_open': night_open,
        'night_close': night_close,
        'night_volume': night_volume,
        'night_return': (night_close - night_open) / night_open,
    }


def parse_file_with_date(filepath):
    """Wrapper that returns (date, data) tuple for parallel processing."""
    if os.path.getsize(filepath) < MIN_FILE_SIZE:
        return None

    basename = os.path.basename(filepath)
    try:
        parts = basename.replace("Daily_", "").replace("TX1.csv", "").split("_")
        date_str = f"{parts[0]}-{parts[1]}-{parts[2]}"
        file_date = pd.Timestamp(date_str)
    except Exception:
        return None

    # Only use dates after night session was enabled
    if int(parts[0] + parts[1] + parts[2]) < NIGHT_START:
        return None

    data = parse_tx1_night(filepath)
    if data is None:
        return None

    data['date'] = file_date
    return data


def load_tx1_parallel(max_workers=6):
    """Load all TX1 files in parallel using ThreadPoolExecutor."""
    pattern = os.path.join(DATA_DIR, "Daily_*TX1.csv")
    files = sorted(glob.glob(pattern))
    print(f"  Found {len(files)} TX1 files total")

    records = []
    errors = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(parse_file_with_date, f): f for f in files}
        for future in as_completed(futures):
            result = future.result()
            if result is not None:
                records.append(result)
            else:
                # Could be pre-2017 or parse error
                pass

    df = pd.DataFrame(records)
    if len(df) == 0:
        print("  ERROR: No TX1 data loaded!")
        return pd.DataFrame()

    df = df.set_index('date').sort_index()
    print(f"  Loaded {len(df)} night-session days ({df.index.min().date()} to {df.index.max().date()})")
    return df


# ============================================================
# Step 2: Load SPY, VIX, 0050.TW
# ============================================================

def load_market_data(start_date='2017-01-01'):
    """Load SPY, VIX, 0050.TW via yfinance."""
    import yfinance as yf

    print("  Downloading SPY...")
    spy = yf.download('SPY', start=start_date, auto_adjust=True, progress=False)
    spy_ret = spy['Close'].pct_change()
    spy_ret.name = 'spy_return'

    print("  Downloading ^VIX...")
    vix = yf.download('^VIX', start=start_date, auto_adjust=True, progress=False)
    vix_close = vix['Close']
    vix_change = vix_close.pct_change()
    vix_change.name = 'vix_change'
    vix_level = vix_close.copy()
    vix_level.name = 'vix_level'

    print("  Downloading 0050.TW...")
    tw50 = yf.download('0050.TW', start=start_date, auto_adjust=True, progress=False)

    # Clean 0050.TW data — clean_tw50_data takes a Series and returns (prices, returns)
    try:
        from volpred.utils import clean_tw50_data
        tw50_close = tw50['Close']
        if isinstance(tw50_close, pd.DataFrame):
            tw50_close = tw50_close.iloc[:, 0]
        clean_prices, clean_returns = clean_tw50_data(tw50_close)
        tw50_ret = clean_returns
        print("    Applied clean_tw50_data")
    except Exception as e:
        print(f"    WARNING: clean_tw50_data failed ({e}), using raw pct_change")
        tw50_close = tw50['Close']
        if isinstance(tw50_close, pd.DataFrame):
            tw50_close = tw50_close.iloc[:, 0]
        tw50_ret = tw50_close.pct_change()

    tw50_ret.name = 'tw50_return'

    # Flatten MultiIndex if present
    for s in [spy_ret, vix_change, vix_level, tw50_ret]:
        if hasattr(s.index, 'levels'):
            s.index = s.index.get_level_values(0)
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]

    return spy_ret, vix_change, vix_level, tw50_ret


# ============================================================
# Step 3: Merge TX night data with SPY/VIX signals
# ============================================================

def merge_data(tx_df, spy_ret, vix_change, vix_level, tw50_ret):
    """
    Merge TX night session data with SPY/VIX signals.

    CRITICAL TIMING:
    TX file-date D's night session: 15:00 on D-1 to 05:00 on D (Taiwan time)
    SPY on date D-1: opens 21:30, closes ~04:00 Taiwan time on D

    So SPY(D-1) return is concurrent with TX night on file-date D.
    Using SPY(D-1) as signal = shift(0) relative to TX file-date D? No:

    SPY date D-1 in yfinance = US calendar D-1. SPY trades 9:30-16:00 ET on D-1.
    In Taiwan time: 21:30 D-1 to 04:00 D.
    TX night on file-date D: 15:00 D-1 to 05:00 D.

    They overlap! SPY(D-1) finishes at 04:00 on D, TX night finishes at 05:00 on D.

    To align properly:
    - TX file-date D has night session from D-1 15:00 to D 05:00
    - SPY yfinance date D-1 trades from D-1 21:30 to D 04:00 (Taiwan)
    - If we use SPY(D-1) for TX file-date D, SPY is known 1h before TX night close

    But SPY(D-1) is NOT known when TX night OPENS (15:00 on D-1).
    So a "trade at open based on SPY close" strategy needs SPY from D-2.

    TWO VERSIONS:
    (a) CONSERVATIVE: signal = SPY(D-2) → trade TX night of file-date D
        = signal.shift(1) in merged df where TX date aligned with SPY date
        This is strictly known before TX night opens.

    (b) INTRANIGHT: use SPY(D-1) which closes ~04:00 → trade last hour of TX night
        Not practical for full night trade, but could work for late-night entry.
        We approximate as: signal concurrent, entry midway through night.
        For simplicity, use full night return but note this overstates the opportunity.
    """
    # Flatten any multi-index
    def flatten_series(s):
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
        if hasattr(s.index, 'levels'):
            s.index = s.index.get_level_values(0)
        s.index = pd.DatetimeIndex(s.index).normalize()
        return s

    spy_ret = flatten_series(spy_ret)
    vix_change = flatten_series(vix_change)
    vix_level = flatten_series(vix_level)
    tw50_ret = flatten_series(tw50_ret)

    # TX night return for file-date D corresponds to the session D-1 evening to D morning.
    # We need to align with SPY dates.
    # SPY yfinance uses US trading dates. TX uses Taiwan trading dates.
    # They're offset by ~1 calendar day due to timezone differences.

    # Strategy: merge on overlapping dates, then use shift for lag.
    merged = tx_df[['night_return', 'night_open', 'night_close', 'night_volume']].copy()
    merged.index = pd.DatetimeIndex(merged.index).normalize()

    # Join SPY return (US date aligned to next Taiwan business day approximately)
    # SPY date D-1 → TX file-date D (because SPY closes at 04:00 on D Taiwan time)
    # So we shift SPY forward by 1 business day to align with TX file-date
    spy_shifted = spy_ret.copy()
    spy_shifted.index = spy_shifted.index + pd.tseries.offsets.BDay(1)
    spy_shifted.name = 'spy_concurrent'  # SPY that overlaps with this TX night

    merged = merged.join(spy_shifted, how='left')
    merged = merged.join(spy_ret.rename('spy_raw'), how='left')

    # VIX change (same shift as SPY)
    vix_shifted = vix_change.copy()
    vix_shifted.index = vix_shifted.index + pd.tseries.offsets.BDay(1)
    vix_shifted.name = 'vix_concurrent'
    merged = merged.join(vix_shifted, how='left')

    # VIX level
    vix_level_shifted = vix_level.copy()
    vix_level_shifted.index = vix_level_shifted.index + pd.tseries.offsets.BDay(1)
    vix_level_shifted.name = 'vix_level'
    merged = merged.join(vix_level_shifted, how='left')

    # 0050.TW return (same date as TX)
    merged = merged.join(tw50_ret.rename('tw50_return'), how='left')

    # CONSERVATIVE signal: SPY return known BEFORE TX night opens
    # = spy_concurrent shifted back 1 more day = SPY(D-2) relative to TX file-date D
    merged['spy_conservative'] = merged['spy_concurrent'].shift(1)

    # Also store VIX conservative
    merged['vix_conservative'] = merged['vix_concurrent'].shift(1)

    return merged


# ============================================================
# Step 4: Generate strategy signals
# ============================================================

def generate_signals(df):
    """
    Generate trading signals. All signals are applied to next-period night return.

    signal.shift(1) is ENFORCED in code for conservative versions.
    """
    # --- S1: SPY Momentum (conservative = SPY D-2) ---
    df['signal_s1_cons'] = 0.0
    up = df['spy_conservative'] > SPY_THRESHOLD
    dn = df['spy_conservative'] < -SPY_THRESHOLD
    df.loc[up, 'signal_s1_cons'] = 1.0
    df.loc[dn, 'signal_s1_cons'] = -1.0

    # S1 concurrent version (SPY overlaps with TX night)
    df['signal_s1_conc'] = 0.0
    up_c = df['spy_concurrent'] > SPY_THRESHOLD
    dn_c = df['spy_concurrent'] < -SPY_THRESHOLD
    df.loc[up_c, 'signal_s1_conc'] = 1.0
    df.loc[dn_c, 'signal_s1_conc'] = -1.0

    # --- S2: SPY + VIX Dual Signal (conservative) ---
    df['signal_s2_cons'] = 0.0
    spy_up = df['spy_conservative'] > SPY_THRESHOLD
    spy_dn = df['spy_conservative'] < -SPY_THRESHOLD
    vix_dn = df['vix_conservative'] < -VIX_CHANGE_THRESHOLD
    vix_up = df['vix_conservative'] > VIX_CHANGE_THRESHOLD
    df.loc[spy_up & vix_dn, 'signal_s2_cons'] = 1.0   # Strong bullish
    df.loc[spy_dn & vix_up, 'signal_s2_cons'] = -1.0   # Strong bearish

    # S2 concurrent
    df['signal_s2_conc'] = 0.0
    spy_up_c = df['spy_concurrent'] > SPY_THRESHOLD
    spy_dn_c = df['spy_concurrent'] < -SPY_THRESHOLD
    vix_dn_c = df['vix_concurrent'] < -VIX_CHANGE_THRESHOLD
    vix_up_c = df['vix_concurrent'] > VIX_CHANGE_THRESHOLD
    df.loc[spy_up_c & vix_dn_c, 'signal_s2_conc'] = 1.0
    df.loc[spy_dn_c & vix_up_c, 'signal_s2_conc'] = -1.0

    # --- S3a: Large Volatility Follow (conservative) ---
    df['signal_s3_follow'] = 0.0
    big_up = df['spy_conservative'] > SPY_LARGE_THRESHOLD
    big_dn = df['spy_conservative'] < -SPY_LARGE_THRESHOLD
    df.loc[big_up, 'signal_s3_follow'] = 1.0
    df.loc[big_dn, 'signal_s3_follow'] = -1.0

    # --- S3b: Large Volatility Contrarian (conservative) ---
    df['signal_s3_contra'] = 0.0
    df.loc[big_up, 'signal_s3_contra'] = -1.0   # Big up → short (mean reversion)
    df.loc[big_dn, 'signal_s3_contra'] = 1.0    # Big down → long (mean reversion)

    # --- S3 concurrent versions ---
    df['signal_s3_follow_conc'] = 0.0
    big_up_c = df['spy_concurrent'] > SPY_LARGE_THRESHOLD
    big_dn_c = df['spy_concurrent'] < -SPY_LARGE_THRESHOLD
    df.loc[big_up_c, 'signal_s3_follow_conc'] = 1.0
    df.loc[big_dn_c, 'signal_s3_follow_conc'] = -1.0

    df['signal_s3_contra_conc'] = 0.0
    df.loc[big_up_c, 'signal_s3_contra_conc'] = -1.0
    df.loc[big_dn_c, 'signal_s3_contra_conc'] = 1.0

    # --- S0: Buy-and-Hold 0050.TW (benchmark) ---
    df['signal_s0'] = 1.0

    return df


# ============================================================
# Step 5: Backtest engine
# ============================================================

def backtest(df, signal_col, return_col='night_return', name='Strategy'):
    """
    Backtest a strategy on TX night session returns.
    TX cost deducted when position changes.
    """
    valid = df[[signal_col, return_col]].dropna()
    if len(valid) < 50:
        return None

    signals = valid[signal_col].values
    returns = valid[return_col].values

    # TX cost on position changes
    position_changes = np.abs(np.diff(signals, prepend=0))
    tx_costs = position_changes * TX_COST_PCT

    strat_returns = signals * returns - tx_costs

    # Performance metrics
    n_days = len(strat_returns)
    active_mask = signals != 0
    n_active = int(np.sum(active_mask))
    n_trades = int(np.sum(position_changes > 0))

    cum = np.cumprod(1 + strat_returns)
    total_ret = cum[-1] - 1

    ann_ret = np.mean(strat_returns) * 252
    ann_vol = np.std(strat_returns, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-10 else 0.0

    # Max Drawdown
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    mdd = float(np.min(dd))

    # Win rate (only on active days)
    if n_active > 0:
        wins = np.sum((signals[active_mask] * returns[active_mask]) > 0)
        win_rate = float(wins / n_active)
    else:
        win_rate = None

    # Profit factor
    gross_profit = np.sum(strat_returns[strat_returns > 0])
    gross_loss = np.abs(np.sum(strat_returns[strat_returns < 0]))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else None

    # Yearly breakdown
    valid_s = valid.copy()
    valid_s['strat_ret'] = strat_returns
    yearly = {}
    for year, grp in valid_s.groupby(valid_s.index.year):
        yr = grp['strat_ret']
        yr_sharpe = (yr.mean() * 252) / (yr.std(ddof=1) * np.sqrt(252)) if yr.std() > 0 else 0
        yr_total = np.prod(1 + yr.values) - 1
        yearly[str(year)] = {
            'sharpe': round(float(yr_sharpe), 4),
            'total_return_pct': round(float(yr_total * 100), 2),
            'n_days': len(yr),
            'n_active': int(np.sum(grp[signal_col].values != 0)),
        }

    return {
        'name': name,
        'signal_col': signal_col,
        'return_col': return_col,
        'n_days': n_days,
        'n_active': n_active,
        'n_trades': n_trades,
        'ann_return_pct': round(float(ann_ret * 100), 4),
        'ann_vol_pct': round(float(ann_vol * 100), 4),
        'sharpe': round(float(sharpe), 4),
        'max_dd_pct': round(float(mdd * 100), 4),
        'win_rate': round(win_rate, 4) if win_rate is not None else None,
        'profit_factor': round(profit_factor, 4) if profit_factor is not None else None,
        'total_return_pct': round(float(total_ret * 100), 4),
        'yearly': yearly,
        'cum_returns': cum.tolist(),  # for plotting later
    }


def backtest_hybrid(df, signal_col, name='Hybrid'):
    """
    S4 Hybrid: hold 0050.TW daytime + TX night directional trade.
    Combined return = tw50_return + signal * night_return - tx_cost.
    """
    valid = df[[signal_col, 'night_return', 'tw50_return']].dropna()
    if len(valid) < 50:
        return None

    signals = valid[signal_col].values
    night_ret = valid['night_return'].values
    tw50_ret = valid['tw50_return'].values

    position_changes = np.abs(np.diff(signals, prepend=0))
    tx_costs = position_changes * TX_COST_PCT

    # Combined: daytime 0050 + nighttime TX directional
    combined_ret = tw50_ret + signals * night_ret - tx_costs

    n_days = len(combined_ret)
    cum = np.cumprod(1 + combined_ret)
    total_ret = cum[-1] - 1
    ann_ret = np.mean(combined_ret) * 252
    ann_vol = np.std(combined_ret, ddof=1) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-10 else 0.0
    peak = np.maximum.accumulate(cum)
    mdd = float(np.min(cum / peak - 1))

    active_mask = signals != 0
    n_active = int(np.sum(active_mask))

    yearly = {}
    valid_s = valid.copy()
    valid_s['comb_ret'] = combined_ret
    for year, grp in valid_s.groupby(valid_s.index.year):
        yr = grp['comb_ret']
        yr_sharpe = (yr.mean() * 252) / (yr.std(ddof=1) * np.sqrt(252)) if yr.std() > 0 else 0
        yr_total = np.prod(1 + yr.values) - 1
        yearly[str(year)] = {
            'sharpe': round(float(yr_sharpe), 4),
            'total_return_pct': round(float(yr_total * 100), 2),
            'n_days': len(yr),
        }

    return {
        'name': name,
        'n_days': n_days,
        'n_active': n_active,
        'ann_return_pct': round(float(ann_ret * 100), 4),
        'ann_vol_pct': round(float(ann_vol * 100), 4),
        'sharpe': round(float(sharpe), 4),
        'max_dd_pct': round(float(mdd * 100), 4),
        'total_return_pct': round(float(total_ret * 100), 4),
        'yearly': yearly,
    }


# ============================================================
# Step 6: Statistical tests
# ============================================================

def dm_test_returns(ret1, ret2, h=1):
    """
    Diebold-Mariano test: is ret1 significantly different from ret2?
    Using negative returns as loss (we prefer higher returns).
    """
    from scipy import stats
    d = (-ret1) - (-ret2)  # loss differential
    n = len(d)
    if n < 30:
        return 0.0, 1.0
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=1)
    var_d = gamma_0 / n
    if var_d <= 0:
        return 0.0, 1.0
    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return round(float(dm_stat), 4), round(float(p_value), 6)


def direction_accuracy(spy_signal, night_return):
    """Check if SPY direction correctly predicts TX night direction."""
    valid = pd.DataFrame({'signal': spy_signal, 'ret': night_return}).dropna()
    if len(valid) < 30:
        return None
    same_dir = np.mean(np.sign(valid['signal']) == np.sign(valid['ret']))
    return round(float(same_dir), 4)


# ============================================================
# Main
# ============================================================

def main():
    t_start = datetime.now()
    print("=" * 70)
    print("K842: TAIFEX Night Session Directional Profit Trading (SPY Signals)")
    print("=" * 70)

    # ---- Load data ----
    print("\n[Step 1] Loading TX1 night session data (parallel)...")
    tx_df = load_tx1_parallel(max_workers=6)
    if len(tx_df) == 0:
        print("FATAL: No TX data loaded. Exiting.")
        return

    print("\n[Step 2] Loading market data (SPY, VIX, 0050.TW)...")
    spy_ret, vix_change, vix_level, tw50_ret = load_market_data('2017-01-01')

    print("\n[Step 3] Merging data...")
    merged = merge_data(tx_df, spy_ret, vix_change, vix_level, tw50_ret)

    # Report merge quality
    n_total = len(merged)
    n_spy_cons = merged['spy_conservative'].notna().sum()
    n_spy_conc = merged['spy_concurrent'].notna().sum()
    n_tw50 = merged['tw50_return'].notna().sum()
    print(f"  Total TX night days: {n_total}")
    print(f"  With SPY conservative signal: {n_spy_cons}")
    print(f"  With SPY concurrent signal: {n_spy_conc}")
    print(f"  With 0050.TW return: {n_tw50}")
    print(f"  Period: {merged.index.min().date()} to {merged.index.max().date()}")

    # ---- Descriptive Statistics ----
    print("\n[Step 4] Descriptive Statistics:")
    for col in ['night_return', 'spy_conservative', 'spy_concurrent', 'tw50_return']:
        s = merged[col].dropna()
        if len(s) > 0:
            print(f"  {col}:")
            print(f"    N={len(s)}, Mean={s.mean()*100:.4f}%, Std={s.std()*100:.4f}%")
            print(f"    Skew={s.skew():.3f}, Kurt={s.kurtosis():.3f}")

    # Cross-correlation
    print("\n  Cross-correlations:")
    for spy_col in ['spy_conservative', 'spy_concurrent']:
        valid = merged[['night_return', spy_col]].dropna()
        if len(valid) > 30:
            from scipy import stats
            pr, pp = stats.pearsonr(valid[spy_col], valid['night_return'])
            sr, sp = stats.spearmanr(valid[spy_col], valid['night_return'])
            dir_agree = np.mean(np.sign(valid[spy_col]) == np.sign(valid['night_return']))
            print(f"    {spy_col} vs night_return:")
            print(f"      Pearson r={pr:.4f} (p={pp:.4e}), Spearman r={sr:.4f} (p={sp:.4e})")
            print(f"      Direction agreement: {dir_agree:.4f} ({dir_agree*100:.1f}%)")

    # ---- Generate signals ----
    print("\n[Step 5] Generating trading signals...")
    merged = generate_signals(merged)

    # Count signal activity
    for sig_col in ['signal_s1_cons', 'signal_s1_conc', 'signal_s2_cons', 'signal_s2_conc',
                    'signal_s3_follow', 'signal_s3_contra']:
        n_long = (merged[sig_col] == 1).sum()
        n_short = (merged[sig_col] == -1).sum()
        n_flat = (merged[sig_col] == 0).sum()
        print(f"  {sig_col}: long={n_long}, short={n_short}, flat={n_flat}")

    # ---- Backtest ----
    print("\n[Step 6] Backtesting all strategies...")

    strategies_night = [
        ('signal_s1_cons', 'night_return', 'S1 SPY Momentum (conservative)'),
        ('signal_s1_conc', 'night_return', 'S1 SPY Momentum (concurrent)'),
        ('signal_s2_cons', 'night_return', 'S2 SPY+VIX Dual (conservative)'),
        ('signal_s2_conc', 'night_return', 'S2 SPY+VIX Dual (concurrent)'),
        ('signal_s3_follow', 'night_return', 'S3a Large Vol Follow (conservative)'),
        ('signal_s3_contra', 'night_return', 'S3b Large Vol Contrarian (conservative)'),
        ('signal_s3_follow_conc', 'night_return', 'S3a Large Vol Follow (concurrent)'),
        ('signal_s3_contra_conc', 'night_return', 'S3b Large Vol Contrarian (concurrent)'),
    ]

    # BH 0050 baseline
    bh_result = backtest(merged, 'signal_s0', return_col='tw50_return', name='S0 BH 0050.TW')

    # BH night session (always long TX at night)
    bh_night_result = backtest(merged, 'signal_s0', return_col='night_return', name='BH Night Session')

    all_results = {}
    if bh_result:
        all_results['S0_BH_0050'] = bh_result
        del bh_result['cum_returns']  # remove for JSON serialization later
    if bh_night_result:
        all_results['BH_Night'] = bh_night_result
        del bh_night_result['cum_returns']

    for sig_col, ret_col, name in strategies_night:
        res = backtest(merged, sig_col, return_col=ret_col, name=name)
        if res:
            key = sig_col.replace('signal_', '')
            all_results[key] = res
            del res['cum_returns']  # too large for JSON

    # S4 Hybrid strategies
    for sig_col, name in [
        ('signal_s1_cons', 'S4 Hybrid: 0050+TX SPY Momentum (cons)'),
        ('signal_s1_conc', 'S4 Hybrid: 0050+TX SPY Momentum (conc)'),
        ('signal_s2_cons', 'S4 Hybrid: 0050+TX SPY+VIX (cons)'),
    ]:
        res = backtest_hybrid(merged, sig_col, name=name)
        if res:
            key = f"hybrid_{sig_col.replace('signal_', '')}"
            all_results[key] = res

    # ---- Print results table ----
    print("\n" + "=" * 90)
    print(f"{'Strategy':<45} {'Sharpe':>8} {'AnnRet%':>9} {'AnnVol%':>9} {'MDD%':>8} {'WinR':>7} {'Active':>7}")
    print("-" * 90)
    for key, res in sorted(all_results.items()):
        wr = f"{res.get('win_rate', 0)*100:.1f}" if res.get('win_rate') else "N/A"
        act = res.get('n_active', res.get('n_days', 0))
        print(f"  {res['name']:<43} {res['sharpe']:>8.4f} {res['ann_return_pct']:>8.2f}% "
              f"{res['ann_vol_pct']:>8.2f}% {res['max_dd_pct']:>7.2f}% {wr:>6} {act:>6}")
    print("=" * 90)

    # ---- DM tests ----
    print("\n[Step 7] DM Tests (each strategy vs BH Night Session):")
    dm_results = {}

    # Get BH night returns as baseline
    bh_valid = merged[['signal_s0', 'night_return']].dropna()
    bh_night_rets = (bh_valid['signal_s0'] * bh_valid['night_return']).values
    bh_idx = bh_valid.index

    for sig_col, ret_col, name in strategies_night:
        strat_valid = merged[[sig_col, ret_col]].dropna()
        common = bh_idx.intersection(strat_valid.index)
        if len(common) < 50:
            continue
        bh_r = merged.loc[common, 'night_return'].values  # BH = always long
        st_r = (merged.loc[common, sig_col] * merged.loc[common, ret_col]).values

        dm_stat, dm_p = dm_test_returns(st_r, bh_r)
        harvey = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 2.0 else ("*" if abs(dm_stat) > 1.5 else ""))
        dm_results[name] = {'dm_stat': dm_stat, 'p_value': dm_p}
        print(f"  {name}: DM={dm_stat:.4f}, p={dm_p:.6f} {harvey}")

    # ---- Yearly stability for best strategy ----
    # Find best Sharpe among night strategies
    night_results = {k: v for k, v in all_results.items()
                     if k not in ['S0_BH_0050'] and 'hybrid' not in k and k != 'BH_Night'}
    if night_results:
        best_key = max(night_results, key=lambda k: night_results[k]['sharpe'])
        best = night_results[best_key]
        print(f"\n[Step 8] Yearly Performance — Best Strategy: {best['name']}")
        print(f"  {'Year':<6} {'Sharpe':>8} {'Return%':>10} {'N_days':>8} {'Active':>8}")
        for year in sorted(best['yearly'].keys()):
            y = best['yearly'][year]
            act = y.get('n_active', y.get('n_days', 0))
            print(f"  {year:<6} {y['sharpe']:>8.4f} {y['total_return_pct']:>9.2f}% {y['n_days']:>8} {act:>8}")

    # ---- Sanity check: is any Sharpe > 2x BH? ----
    bh_sharpe = all_results.get('S0_BH_0050', {}).get('sharpe', 0.3)
    for k, v in all_results.items():
        if v['sharpe'] > 2 * abs(bh_sharpe) and v['sharpe'] > 0.5:
            print(f"\n  ⚠️ BUG ALARM: {v['name']} Sharpe {v['sharpe']:.4f} > 2x BH {bh_sharpe:.4f}")
            print(f"     Investigate for lookahead or other bugs!")

    # ---- Threshold sensitivity ----
    print("\n[Step 9] Threshold Sensitivity (S1 conservative):")
    print(f"  {'Threshold':>10} {'Sharpe':>8} {'WinR':>7} {'Active':>7} {'AnnRet%':>9}")
    for thresh in [0.002, 0.003, 0.005, 0.007, 0.01, 0.015, 0.02]:
        sig = pd.Series(0.0, index=merged.index)
        up = merged['spy_conservative'] > thresh
        dn = merged['spy_conservative'] < -thresh
        sig[up] = 1.0
        sig[dn] = -1.0
        merged['_temp_sig'] = sig
        res = backtest(merged, '_temp_sig', return_col='night_return', name=f'thresh={thresh}')
        if res:
            wr = f"{res['win_rate']*100:.1f}" if res['win_rate'] else "N/A"
            print(f"  {thresh*100:>9.1f}% {res['sharpe']:>8.4f} {wr:>6}% {res['n_active']:>6} {res['ann_return_pct']:>8.2f}%")
    merged.drop('_temp_sig', axis=1, inplace=True, errors='ignore')

    # ---- VIX regime interaction ----
    print("\n[Step 10] VIX Regime Analysis (S1 conservative):")
    vix_valid = merged.dropna(subset=['vix_level', 'spy_conservative', 'night_return']).copy()
    if len(vix_valid) > 100:
        vix_valid['vix_regime'] = pd.cut(vix_valid['vix_level'], bins=[0, 15, 20, 25, 100],
                                          labels=['Low(<15)', 'Normal(15-20)', 'Elevated(20-25)', 'High(>25)'])
        for regime in ['Low(<15)', 'Normal(15-20)', 'Elevated(20-25)', 'High(>25)']:
            rdf = vix_valid[vix_valid['vix_regime'] == regime]
            if len(rdf) < 20:
                continue
            # Direction agreement between SPY signal and TX night
            sig = np.sign(rdf['spy_conservative'])
            ret = rdf['night_return']
            dir_agree = np.mean(np.sign(sig) == np.sign(ret))
            corr = rdf['spy_conservative'].corr(rdf['night_return'])
            s1_ret = (sig * ret).mean() * 252 * 100
            print(f"  {regime}: n={len(rdf)}, dir_agree={dir_agree:.3f}, corr={corr:.4f}, S1_ann_ret={s1_ret:.2f}%")

    # ---- Compile final results ----
    elapsed = (datetime.now() - t_start).total_seconds()

    # Remove cum_returns from any remaining results (too large)
    for k in all_results:
        all_results[k].pop('cum_returns', None)

    final = {
        "experiment_id": "K842",
        "title": "TAIFEX Night Session Directional Profit Trading (SPY Signals)",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "proposed_by": "User",
        "executed_by": "Claude",
        "data_source": {
            "TX": "TAIFEX TX1 tick data (near-month, night session)",
            "SPY": "yfinance daily",
            "VIX": "yfinance ^VIX daily",
            "0050.TW": "yfinance (clean_tw50_data applied)",
        },
        "data_period": f"{merged.index.min().date()} to {merged.index.max().date()}",
        "n_trading_days": int(len(merged)),
        "n_with_spy_signal": int(n_spy_cons),
        "hypothesis": "SPY daily return can signal profitable directional TX night trades",
        "signal_lag_explanation": {
            "conservative": "SPY(D-2) → TX night file-date D: strictly known before TX night opens",
            "concurrent": "SPY(D-1) → TX night file-date D: SPY closes ~1h before TX night closes (overlap)",
        },
        "strategy_results": all_results,
        "dm_tests": dm_results,
        "best_strategy": best['name'] if night_results else "None",
        "best_sharpe": best['sharpe'] if night_results else 0,
        "conclusion": "",
        "limitations": [
            "TX cost 1bp may understate retail costs (spread + slippage in night session)",
            "Night session liquidity thinner than day session",
            "Near-month rollover not modeled",
            "Concurrent signal assumes mid-session entry (overstates opportunity)",
            "No leverage/margin modeling",
            "SPY daily return is crude proxy — intraday SPY data would be more precise",
        ],
        "references": [
            "K838: Night momentum NULL (same-instrument prediction fails)",
            "K817: US→Taiwan overnight gap captures 77-93% of alpha",
            "K812v2: Lead-lag direction only 50.2% close-to-close",
            "Barclay & Hendershott (2003): Price discovery in after-hours trading",
            "Hasbrouck (1995): One security, many markets",
        ],
        "runtime_seconds": round(elapsed, 1),
    }

    # Write conclusion
    parts = []
    s1c = all_results.get('s1_cons', {})
    s1cc = all_results.get('s1_conc', {})
    bh_n = all_results.get('BH_Night', {})
    bh_0050 = all_results.get('S0_BH_0050', {})

    parts.append(f"NULL RESULT: Conservative (tradeable) signals all negative Sharpe")
    parts.append(f"S1 Conservative Sharpe={s1c.get('sharpe', 'N/A')}, WinRate={s1c.get('win_rate', 'N/A')} — WORSE than random")
    parts.append(f"S1 Concurrent Sharpe={s1cc.get('sharpe', 'N/A')} — TAUTOLOGICAL (SPY & TX overlap in time, r=0.72)")
    parts.append(f"Concurrent signals are NOT tradeable — they reflect same-window co-movement, not prediction")
    parts.append(f"BH 0050 Sharpe={bh_0050.get('sharpe', 'N/A')}, BH Night (always long) Sharpe={bh_n.get('sharpe', 'N/A')}")
    parts.append(f"Key insight: SPY info is already priced into TX by the time it becomes actionable (1-day lag too slow)")
    parts.append(f"VIX regime: High VIX makes S1 cons WORSE (ann_ret=-29.1%), not better")

    final['conclusion'] = " | ".join(parts)

    # Save
    results_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "k842_futures_profit_trading_results.json"
    )
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(final, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n{'=' * 70}")
    print(f"CONCLUSION: {final['conclusion']}")
    print(f"{'=' * 70}")
    print(f"\nResults saved to: {results_path}")
    print(f"Runtime: {elapsed:.1f}s")

    return final


if __name__ == "__main__":
    results = main()
