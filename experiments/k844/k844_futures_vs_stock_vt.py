#!/usr/bin/env python3
"""
K844: TX Futures VT vs 0050.TW Stock VT
========================================
Core hypothesis (proposed by user):
  0050.TW only trades 09:00-13:30 (4.5 hours) but close-to-close returns
  include overnight gaps. K817 found 77-93% of US→TW alpha is in overnight gaps
  — untradable with 0050.TW ETF.

  TX futures trade 08:45-13:45 + 15:00-05:00 (20.25 hours), covering nearly
  the full day including US market hours.

  Hypothesis: 8.63/VIX strategy executed via TX futures should capture more
  return than via 0050.TW ETF.

Strategies:
  S0:  Buy-and-Hold 0050.TW (baseline)
  S0b: Buy-and-Hold TX Futures (full-day return)
  S1:  8.63/VIX on 0050.TW close-to-close (existing strategy)
  S2:  8.63/VIX on TX Futures full-day return
  S3:  8.63/VIX on TX Futures night session only
  S4:  Split VT — day session TX + night session TX, separate weights

Signal timing:
  - VIX(T-1) = most recent US VIX close before Taiwan date T
  - signal.shift(1) enforced: weight on day T uses VIX from T-1
  - Night session for date T starts at 15:00 on T-1 → needs VIX(T-2)

TX Return definitions:
  - night_return = (night_close - night_open) / night_open
  - day_return = (day_close - day_open) / day_open
  - gap_return = (day_open - night_close) / night_close  (gap between sessions)
  - full_day_return ≈ (day_close_T - day_close_{T-1}) / day_close_{T-1}
    OR more precisely: (1+night_ret)*(1+gap_ret)*(1+day_ret) - 1

TX Cost: 2 ticks round-trip ≈ 0.01% (vs 0050.TW ~0.34%)
0050.TW Cost: 0.1425% commission + 0.1% tax ≈ 0.34% round-trip

Error log rules applied:
  - 0050.TW: must use clean_tw50_data
  - signal.shift(1): VIX uses previous day
  - Futures basis (contango/backwardation) tracked
  - Near-month contract by max volume
  - Only use data from 2017-05-16 (night session start)

References:
  - K817: US→Taiwan spillover, 77-93% alpha in overnight gap
  - K812v2: Lead-lag with OTC returns
  - K838: Night session momentum
  - K841: Night session real-time VT hedging

[提出: 用戶(核心觀察: 0050.TW 無法交易隔夜 gap), 執行: Claude]
Author: VolPred Research System
Date: 2026-04-03
"""

import os
import sys
import json
import glob
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from concurrent.futures import ProcessPoolExecutor, as_completed
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
TAIFEX_DIR = '/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python'
NIGHT_SESSION_START_DATE = 20170516  # Night session began 2017-05-15
VIX_ANCHOR = 8.63  # Taiwan VT anchor
MIN_FILE_SIZE = 100
FUTURES_TX_COST_PCT = 0.0001  # 2 ticks round-trip ≈ 0.01%
STOCK_TX_COST_PCT = 0.0034   # 0.34% round-trip for 0050.TW
WEIGHT_CHANGE_THRESHOLD = 0.02  # Minimum weight change to trigger trade

# Time boundaries (HHMMSS format)
NIGHT_PM_START = 150000
NIGHT_PM_END = 235959
NIGHT_AM_START = 0
NIGHT_AM_END = 50000
DAY_START = 84500
DAY_END = 134500

# ============================================================
# Step 1: Parse TX files
# ============================================================

def parse_tx_file(filepath):
    """Parse a TX file, extract night/day session prices for near-month contract."""
    try:
        fsize = os.path.getsize(filepath)
        if fsize < MIN_FILE_SIZE:
            return None

        df = pd.read_csv(filepath, encoding='big5', low_memory=False)
        if len(df) < 2:
            return None

        # Standardize: filter to TX product
        col_product = df.columns[1]  # 商品代號
        df = df[df[col_product].str.strip() == 'TX']
        if df.empty:
            return None

        col_date = df.columns[0]      # 成交日期
        col_expiry = df.columns[2]    # 到期月份(週別)
        col_time = df.columns[3]      # 成交時間
        col_price = df.columns[4]     # 成交價格
        col_volume = df.columns[5]    # 成交數量(B+S)

        # Convert types
        df['price'] = pd.to_numeric(df[col_price], errors='coerce')
        df['volume'] = pd.to_numeric(df[col_volume].apply(lambda x: str(x).replace(',', '')), errors='coerce')
        df['time_int'] = pd.to_numeric(df[col_time], errors='coerce').astype('Int64')
        df['trade_date'] = pd.to_numeric(df[col_date], errors='coerce').astype('Int64')
        df['expiry'] = df[col_expiry].astype(str).str.strip()
        df = df.dropna(subset=['price', 'time_int'])

        if len(df) == 0:
            return None

        # Near-month: highest total volume expiry
        vol_by_exp = df.groupby('expiry')['volume'].sum()
        near_month = vol_by_exp.idxmax()
        df = df[df['expiry'] == near_month].copy()

        # Extract file date
        basename = os.path.basename(filepath)
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        file_date_str = ''.join(parts)
        file_date = int(file_date_str)

        t = df['time_int'].values
        prices = df['price'].values
        volumes = df['volume'].values

        result = {
            'file_date': file_date,
            'near_month': near_month,
        }

        # === Night session (PM: 15:00-23:59 + AM: 00:00-05:00) ===
        night_pm_mask = (t >= NIGHT_PM_START) & (t <= NIGHT_PM_END)
        night_am_mask = (t >= NIGHT_AM_START) & (t <= NIGHT_AM_END)
        night_mask = night_pm_mask | night_am_mask

        night_prices = prices[night_mask]
        night_volumes = volumes[night_mask]
        night_times = t[night_mask]

        if len(night_prices) >= 2:
            # Sort by time: PM first (15:xx), then AM (00:xx-05:xx)
            # PM times are larger numbers, so we need to handle wrap-around
            sort_key = np.where(night_times >= NIGHT_PM_START, night_times - 240000, night_times)
            sort_idx = np.argsort(sort_key)
            night_prices = night_prices[sort_idx]
            night_volumes = night_volumes[sort_idx]

            result['night_open'] = float(night_prices[0])
            result['night_close'] = float(night_prices[-1])
            result['night_high'] = float(np.max(night_prices))
            result['night_low'] = float(np.min(night_prices))
            result['night_volume'] = float(np.nansum(night_volumes))
            result['night_ticks'] = int(len(night_prices))

        # === Day session (08:45-13:45) ===
        day_mask = (t >= DAY_START) & (t <= DAY_END)
        day_prices = prices[day_mask]
        day_volumes = volumes[day_mask]
        day_times = t[day_mask]

        if len(day_prices) >= 2:
            sort_idx = np.argsort(day_times)
            day_prices = day_prices[sort_idx]
            day_volumes = day_volumes[sort_idx]

            result['day_open'] = float(day_prices[0])
            result['day_close'] = float(day_prices[-1])
            result['day_high'] = float(np.max(day_prices))
            result['day_low'] = float(np.min(day_prices))
            result['day_volume'] = float(np.nansum(day_volumes))
            result['day_ticks'] = int(len(day_prices))

        return result

    except Exception as e:
        return None


def load_tx_data(n_workers=8):
    """Load all TX files in parallel, return DataFrame."""
    pattern = os.path.join(TAIFEX_DIR, 'Daily_*TX.csv')
    all_files = sorted(glob.glob(pattern))

    # Filter: only main TX files (not TX1, TX2), >= night session start
    valid_files = []
    for f in all_files:
        basename = os.path.basename(f)
        if not basename.endswith('TX.csv'):
            continue
        parts = basename.replace('Daily_', '').replace('TX.csv', '').split('_')
        try:
            fdate = int(''.join(parts))
            if fdate >= NIGHT_SESSION_START_DATE:
                valid_files.append(f)
        except ValueError:
            continue

    print(f"Loading {len(valid_files)} TX files from {NIGHT_SESSION_START_DATE}...")
    t0 = time.time()

    results = []
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(parse_tx_file, f): f for f in valid_files}
        for future in as_completed(futures):
            r = future.result()
            if r is not None:
                results.append(r)

    tx_df = pd.DataFrame(results)
    tx_df = tx_df.sort_values('file_date').reset_index(drop=True)
    elapsed = time.time() - t0
    print(f"  Loaded {len(tx_df)} trading days in {elapsed:.1f}s")

    # Convert to datetime
    tx_df['date'] = pd.to_datetime(tx_df['file_date'].astype(str), format='%Y%m%d')
    return tx_df


def load_market_data():
    """Load VIX and 0050.TW from yfinance."""
    import yfinance as yf
    from volpred.utils import clean_tw50_data

    print("\nLoading VIX and 0050.TW from yfinance...")

    # VIX
    vix = yf.download('^VIX', start='2017-01-01', end='2026-12-31', progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_close = vix['Close'].squeeze()
    if isinstance(vix_close, pd.DataFrame):
        vix_close = vix_close.iloc[:, 0]
    vix_close.index = pd.to_datetime(vix_close.index).tz_localize(None)

    # 0050.TW
    tw50 = yf.download('0050.TW', start='2017-01-01', end='2026-12-31', progress=False)
    if isinstance(tw50.columns, pd.MultiIndex):
        tw50.columns = tw50.columns.get_level_values(0)
    tw50_close = tw50['Close'].squeeze()
    if isinstance(tw50_close, pd.DataFrame):
        tw50_close = tw50_close.iloc[:, 0]
    tw50_close.index = pd.to_datetime(tw50_close.index).tz_localize(None)

    clean_prices, clean_returns = clean_tw50_data(tw50_close)

    print(f"  VIX: {len(vix_close)} days, 0050.TW: {len(clean_prices)} days")
    return vix_close, clean_prices, clean_returns


# ============================================================
# Main execution
# ============================================================
if __name__ == '__main__':
    print("=" * 70)
    print("K844: TX Futures VT vs 0050.TW Stock VT")
    print("=" * 70)

    # Load data
    tx_df = load_tx_data(n_workers=8)
    vix_close, tw50_prices, tw50_returns = load_market_data()

    # ============================================================
    # Step 2: Compute TX session returns
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 2: Computing TX session returns")
    print("=" * 70)

    # Night return: (night_close - night_open) / night_open
    tx_df['night_ret'] = np.where(
        tx_df['night_open'].notna() & (tx_df['night_open'] > 0),
        (tx_df['night_close'] - tx_df['night_open']) / tx_df['night_open'],
        np.nan
    )

    # Day return: (day_close - day_open) / day_open
    tx_df['day_ret'] = np.where(
        tx_df['day_open'].notna() & (tx_df['day_open'] > 0),
        (tx_df['day_close'] - tx_df['day_open']) / tx_df['day_open'],
        np.nan
    )

    # Gap return: (day_open - night_close) / night_close
    tx_df['gap_ret'] = np.where(
        tx_df['night_close'].notna() & tx_df['day_open'].notna() & (tx_df['night_close'] > 0),
        (tx_df['day_open'] - tx_df['night_close']) / tx_df['night_close'],
        np.nan
    )

    # Full-day return (compounded): (1+night)*(1+gap)*(1+day) - 1
    tx_df['full_day_ret'] = np.where(
        tx_df['night_ret'].notna() & tx_df['gap_ret'].notna() & tx_df['day_ret'].notna(),
        (1 + tx_df['night_ret']) * (1 + tx_df['gap_ret']) * (1 + tx_df['day_ret']) - 1,
        np.nan
    )

    # TX close-to-close return (day_close to day_close)
    tx_df['tx_c2c_ret'] = tx_df['day_close'].pct_change()

    # Basis: TX day_close vs 0050.TW close (will be computed after merge)

    valid_tx = tx_df.dropna(subset=['night_ret', 'day_ret', 'gap_ret'])
    print(f"\nTX data: {len(tx_df)} total days, {len(valid_tx)} with complete session data")
    print(f"  Night return: mean={valid_tx['night_ret'].mean()*100:.4f}%, std={valid_tx['night_ret'].std()*100:.4f}%")
    print(f"  Gap return:   mean={valid_tx['gap_ret'].mean()*100:.4f}%, std={valid_tx['gap_ret'].std()*100:.4f}%")
    print(f"  Day return:   mean={valid_tx['day_ret'].mean()*100:.4f}%, std={valid_tx['day_ret'].std()*100:.4f}%")
    print(f"  Full-day ret: mean={valid_tx['full_day_ret'].mean()*100:.4f}%, std={valid_tx['full_day_ret'].std()*100:.4f}%")
    print(f"  TX c2c ret:   mean={valid_tx['tx_c2c_ret'].mean()*100:.4f}%, std={valid_tx['tx_c2c_ret'].std()*100:.4f}%")

    # Return decomposition
    total_mean = valid_tx['full_day_ret'].mean()
    night_pct = valid_tx['night_ret'].mean() / total_mean * 100 if total_mean != 0 else np.nan
    gap_pct = valid_tx['gap_ret'].mean() / total_mean * 100 if total_mean != 0 else np.nan
    day_pct = valid_tx['day_ret'].mean() / total_mean * 100 if total_mean != 0 else np.nan
    print(f"\n  Return decomposition (% of full-day return):")
    print(f"    Night session: {night_pct:.1f}%")
    print(f"    Gap (night→day): {gap_pct:.1f}%")
    print(f"    Day session: {day_pct:.1f}%")

    # ============================================================
    # Step 3: Merge TX + VIX + 0050.TW
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 3: Merging datasets")
    print("=" * 70)

    merged = tx_df[['date', 'night_open', 'night_close', 'day_open', 'day_close',
                     'night_ret', 'day_ret', 'gap_ret', 'full_day_ret', 'tx_c2c_ret',
                     'night_volume', 'day_volume']].copy()
    merged = merged.set_index('date')

    # Add VIX (T-1): most recent US close before Taiwan date T
    vix_series = vix_close.copy()
    vix_dates = sorted(vix_series.index)

    # For each Taiwan trading date, find the most recent VIX close
    vix_for_day = {}    # VIX(T-1) for day session signal
    vix_for_night = {}  # VIX(T-2) for night session signal

    for date in merged.index:
        prev_vix = [d for d in vix_dates if d < date]
        if len(prev_vix) >= 1:
            vix_for_day[date] = float(vix_series.loc[prev_vix[-1]])
        if len(prev_vix) >= 2:
            vix_for_night[date] = float(vix_series.loc[prev_vix[-2]])

    merged['vix_t1'] = pd.Series(vix_for_day)   # VIX(T-1)
    merged['vix_t2'] = pd.Series(vix_for_night)  # VIX(T-2)

    # Add 0050.TW close-to-close return
    tw50_ret_series = tw50_returns.copy()
    tw50_ret_series.index = pd.to_datetime(tw50_ret_series.index).tz_localize(None)
    tw50_price_series = tw50_prices.copy()
    tw50_price_series.index = pd.to_datetime(tw50_price_series.index).tz_localize(None)

    merged['tw50_ret'] = tw50_ret_series.reindex(merged.index)
    merged['tw50_close'] = tw50_price_series.reindex(merged.index)

    # Basis: (TX day_close / 0050_close * point_value_ratio) - 1
    # TX is index points, 0050 is ETF price. We compare returns, not levels.

    # Drop rows missing critical data
    merged_full = merged.dropna(subset=['vix_t1', 'tw50_ret', 'night_ret', 'day_ret', 'gap_ret']).copy()
    print(f"Merged dataset: {len(merged_full)} trading days")
    print(f"  Period: {merged_full.index[0].date()} to {merged_full.index[-1].date()}")

    # ============================================================
    # Step 4: Return comparison (TX vs 0050.TW)
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 4: TX vs 0050.TW Return Comparison")
    print("=" * 70)

    # TX close-to-close vs 0050.TW close-to-close
    tx_ret = merged_full['tx_c2c_ret']
    tw_ret = merged_full['tw50_ret']
    full_ret = merged_full['full_day_ret']

    corr_c2c = tx_ret.corr(tw_ret)
    corr_full = full_ret.corr(tw_ret)
    mean_diff_c2c = (tx_ret - tw_ret).mean() * 252 * 100  # annualized bp
    mean_diff_full = (full_ret - tw_ret).mean() * 252 * 100

    print(f"\n  TX c2c vs 0050 c2c correlation: {corr_c2c:.4f}")
    print(f"  TX full-day vs 0050 c2c correlation: {corr_full:.4f}")
    print(f"  TX c2c - 0050 mean diff (ann.): {mean_diff_c2c:.2f} bps")
    print(f"  TX full-day - 0050 mean diff (ann.): {mean_diff_full:.2f} bps")

    # Basis tracking (TX day_close vs expected 0050 level)
    # Positive = TX trades at premium (contango)
    tx_day_close = merged_full['day_close']
    tw50_close_aligned = merged_full['tw50_close']
    # Normalize to first day for comparison
    tx_norm = tx_day_close / tx_day_close.iloc[0]
    tw_norm = tw50_close_aligned / tw50_close_aligned.iloc[0]
    cum_basis_drift = (tx_norm.iloc[-1] / tw_norm.iloc[-1] - 1) * 100
    print(f"\n  Cumulative basis drift (TX vs 0050 normalized): {cum_basis_drift:.2f}%")
    print(f"  Annualized basis drift: {cum_basis_drift / (len(merged_full)/252):.2f}%/yr")

    # ============================================================
    # Step 5: Strategy comparison
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 5: Strategy Comparison")
    print("=" * 70)

    # VIX weights: signal.shift(1) = use VIX(T-1) for day T
    # For 0050.TW and TX day strategies: VIX(T-1) is available before 08:45 Taiwan
    # For TX night strategies: VIX(T-2) needed (night starts 15:00 on T-1)
    merged_full['weight_day'] = np.minimum(VIX_ANCHOR / merged_full['vix_t1'], 1.0)
    merged_full['weight_night'] = np.minimum(VIX_ANCHOR / merged_full['vix_t2'].fillna(merged_full['vix_t1']), 1.0)

    # === S0: Buy & Hold 0050.TW ===
    merged_full['s0_ret'] = merged_full['tw50_ret']

    # === S0b: Buy & Hold TX Futures (full-day) ===
    merged_full['s0b_ret'] = merged_full['full_day_ret']

    # === S1: 8.63/VIX on 0050.TW ===
    # Weight on day T uses VIX(T-1), applied to 0050 close-to-close return on day T
    # TX cost: weight change * stock TX cost
    w_s1 = merged_full['weight_day'].copy()
    s1_tc = abs(w_s1 - w_s1.shift(1).fillna(1.0)) * STOCK_TX_COST_PCT
    merged_full['s1_ret'] = w_s1 * merged_full['tw50_ret'] - s1_tc

    # === S2: 8.63/VIX on TX Futures full-day ===
    # Same weight timing as S1, applied to TX full-day return
    # TX cost: weight change * futures TX cost (much cheaper)
    w_s2 = merged_full['weight_day'].copy()
    s2_tc = abs(w_s2 - w_s2.shift(1).fillna(1.0)) * FUTURES_TX_COST_PCT
    merged_full['s2_ret'] = w_s2 * merged_full['full_day_ret'] - s2_tc

    # === S3: 8.63/VIX on TX night session only ===
    # Use VIX(T-2) for night weight (night starts before VIX(T-1) is available)
    w_s3 = merged_full['weight_night'].copy()
    s3_tc = abs(w_s3 - w_s3.shift(1).fillna(1.0)) * FUTURES_TX_COST_PCT
    merged_full['s3_ret'] = w_s3 * merged_full['night_ret'] - s3_tc

    # === S4: Split VT (day TX + night TX with separate weights) ===
    # Day: VIX(T-1) weight on TX day return
    # Night: VIX(T-2) weight on TX night return
    # Gap: assume gap is captured proportional to overnight position
    w_day = merged_full['weight_day'].copy()
    w_night = merged_full['weight_night'].copy()
    s4_day_ret = w_day * merged_full['day_ret']
    s4_night_ret = w_night * merged_full['night_ret']
    s4_gap_ret = w_night * merged_full['gap_ret']  # Gap follows overnight position
    s4_tc = (abs(w_day - w_day.shift(1).fillna(1.0)) + abs(w_night - w_night.shift(1).fillna(1.0))) * FUTURES_TX_COST_PCT
    merged_full['s4_ret'] = s4_night_ret + s4_gap_ret + s4_day_ret - s4_tc

    # ============================================================
    # Step 6: Performance metrics
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 6: Performance Metrics")
    print("=" * 70)

    strategies = {
        'S0: BH 0050.TW': 's0_ret',
        'S0b: BH TX Full-Day': 's0b_ret',
        'S1: 8.63/VIX on 0050.TW': 's1_ret',
        'S2: 8.63/VIX on TX Full-Day': 's2_ret',
        'S3: 8.63/VIX on TX Night': 's3_ret',
        'S4: Split VT (Day+Night)': 's4_ret',
    }

    perf_results = {}
    for name, col in strategies.items():
        rets = merged_full[col].dropna()
        n = len(rets)
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + rets).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        total_ret = cum.iloc[-1] - 1
        years = n / 252
        cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0
        calmar = cagr / abs(mdd) if mdd != 0 else 0

        # Turnover (average daily absolute weight change)
        w_col = None
        if 's1' in col:
            w_col = w_s1
        elif 's2' in col:
            w_col = w_s2
        elif 's3' in col:
            w_col = w_s3
        elif 's4' in col:
            turnover = (abs(w_day - w_day.shift(1).fillna(1.0)).mean() +
                        abs(w_night - w_night.shift(1).fillna(1.0)).mean())
        else:
            turnover = 0.0

        if w_col is not None:
            turnover = abs(w_col - w_col.shift(1).fillna(1.0)).mean()

        perf_results[name] = {
            'n_days': n,
            'ann_return': float(ann_ret),
            'ann_vol': float(ann_vol),
            'sharpe': float(sharpe),
            'mdd': float(mdd),
            'cagr': float(cagr),
            'total_return': float(total_ret),
            'calmar': float(calmar),
            'avg_daily_turnover': float(turnover) if 'turnover' in dir() else 0.0,
        }

        print(f"\n  {name}:")
        print(f"    Ann Return: {ann_ret*100:.2f}%  |  Ann Vol: {ann_vol*100:.2f}%")
        print(f"    Sharpe: {sharpe:.3f}  |  MDD: {mdd*100:.2f}%  |  CAGR: {cagr*100:.2f}%")
        print(f"    Total Return: {total_ret*100:.1f}%  |  Calmar: {calmar:.3f}")

    # ============================================================
    # Step 7: DM tests (S2 vs S1, S4 vs S1)
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 7: Diebold-Mariano Tests")
    print("=" * 70)

    from volpred.stats.model_evaluation import strategy_dm_test

    dm_results = {}
    comparisons = [
        ('S2 vs S1', 's2_ret', 's1_ret'),
        ('S4 vs S1', 's4_ret', 's1_ret'),
        ('S0b vs S0', 's0b_ret', 's0_ret'),
        ('S2 vs S0', 's2_ret', 's0_ret'),
        ('S3 vs S1', 's3_ret', 's1_ret'),
    ]

    for label, col_a, col_b in comparisons:
        ret_a = merged_full[col_a].dropna()
        ret_b = merged_full[col_b].dropna()
        common_idx = ret_a.index.intersection(ret_b.index)
        ret_a = ret_a.loc[common_idx]
        ret_b = ret_b.loc[common_idx]

        try:
            dm_stat, dm_pval = strategy_dm_test(ret_a.values, ret_b.values)
            harvey_pass = abs(dm_stat) > 3.0
            dm_results[label] = {
                'dm_stat': float(dm_stat),
                'p_value': float(dm_pval),
                'harvey_pass': harvey_pass,
            }
            print(f"  {label}: DM stat={dm_stat:.3f}, p={dm_pval:.4f}, Harvey t>3.0: {'PASS' if harvey_pass else 'FAIL'}")
        except Exception as e:
            print(f"  {label}: DM test failed - {e}")
            # Fallback: simple t-test on return differences
            diff = ret_a.values - ret_b.values
            t_stat, p_val = stats.ttest_1samp(diff, 0)
            dm_results[label] = {
                'dm_stat': float(t_stat),
                'p_value': float(p_val),
                'harvey_pass': abs(t_stat) > 3.0,
                'note': 'fallback t-test'
            }
            print(f"  {label}: t-test stat={t_stat:.3f}, p={p_val:.4f}, Harvey: {'PASS' if abs(t_stat) > 3.0 else 'FAIL'}")

    # ============================================================
    # Step 8: Return decomposition analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 8: Return Decomposition Analysis")
    print("=" * 70)

    night_mean = merged_full['night_ret'].mean() * 252
    gap_mean = merged_full['gap_ret'].mean() * 252
    day_mean = merged_full['day_ret'].mean() * 252
    full_mean = merged_full['full_day_ret'].mean() * 252
    tw50_mean = merged_full['tw50_ret'].mean() * 252

    print(f"\n  Annualized returns (bp):")
    print(f"    TX Night session:     {night_mean*10000:.1f} bp")
    print(f"    TX Gap (night→day):   {gap_mean*10000:.1f} bp")
    print(f"    TX Day session:       {day_mean*10000:.1f} bp")
    print(f"    TX Full-day total:    {full_mean*10000:.1f} bp")
    print(f"    0050.TW c2c:          {tw50_mean*10000:.1f} bp")
    print(f"    TX full-day - 0050:   {(full_mean-tw50_mean)*10000:.1f} bp")

    # VIX regime analysis
    print(f"\n  VIX Regime Analysis:")
    for regime, (vix_low, vix_high) in [('Low (<15)', (0, 15)), ('Medium (15-25)', (15, 25)), ('High (>25)', (25, 100))]:
        mask = (merged_full['vix_t1'] >= vix_low) & (merged_full['vix_t1'] < vix_high)
        if mask.sum() > 20:
            n_days = mask.sum()
            night_r = merged_full.loc[mask, 'night_ret'].mean() * 252 * 10000
            gap_r = merged_full.loc[mask, 'gap_ret'].mean() * 252 * 10000
            day_r = merged_full.loc[mask, 'day_ret'].mean() * 252 * 10000
            full_r = merged_full.loc[mask, 'full_day_ret'].mean() * 252 * 10000
            tw_r = merged_full.loc[mask, 'tw50_ret'].mean() * 252 * 10000
            s1_r = merged_full.loc[mask, 's1_ret'].mean() * 252 * 10000
            s2_r = merged_full.loc[mask, 's2_ret'].mean() * 252 * 10000
            print(f"\n  {regime} ({n_days} days):")
            print(f"    Night: {night_r:.0f}bp, Gap: {gap_r:.0f}bp, Day: {day_r:.0f}bp, Full: {full_r:.0f}bp")
            print(f"    0050 c2c: {tw_r:.0f}bp | S1(0050): {s1_r:.0f}bp | S2(TX): {s2_r:.0f}bp")

    # ============================================================
    # Step 9: TX cost advantage analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 9: Transaction Cost Advantage")
    print("=" * 70)

    # Calculate actual TX costs paid by each strategy
    tc_s1 = abs(w_s1 - w_s1.shift(1).fillna(1.0)).sum() * STOCK_TX_COST_PCT
    tc_s2 = abs(w_s2 - w_s2.shift(1).fillna(1.0)).sum() * FUTURES_TX_COST_PCT
    years = len(merged_full) / 252

    print(f"\n  Total TX costs over {years:.1f} years:")
    print(f"    S1 (0050.TW, {STOCK_TX_COST_PCT*100:.2f}%): {tc_s1*100:.2f}%")
    print(f"    S2 (TX futures, {FUTURES_TX_COST_PCT*100:.3f}%): {tc_s2*100:.4f}%")
    print(f"    Cost saving: {(tc_s1-tc_s2)*100:.2f}% ({(tc_s1-tc_s2)/tc_s1*100:.1f}% reduction)")
    print(f"    Annualized cost saving: {(tc_s1-tc_s2)/years*100:.3f}%/yr = {(tc_s1-tc_s2)/years*10000:.1f} bp/yr")

    # ============================================================
    # Step 10: Cross-OOS validation
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 10: Cross-OOS Validation")
    print("=" * 70)

    # Define 5 non-overlapping 2-year periods
    oos_periods = [
        ('2018-01', '2019-12'),
        ('2020-01', '2021-12'),
        ('2022-01', '2023-12'),
        ('2024-01', '2025-12'),
        # ('2026-01', '2026-12'),  # partial year, skip
    ]

    oos_results = {}
    s2_wins = 0
    s4_wins = 0

    for start, end in oos_periods:
        mask = (merged_full.index >= start) & (merged_full.index <= end)
        if mask.sum() < 100:
            continue

        sub = merged_full.loc[mask]
        label = f"{start} to {end}"

        # Sharpe for each strategy
        s_results = {}
        for sname, col in strategies.items():
            rets = sub[col].dropna()
            if len(rets) > 50:
                sharpe = rets.mean() / rets.std() * np.sqrt(252)
                mdd = ((1 + rets).cumprod() / (1 + rets).cumprod().cummax() - 1).min()
                s_results[sname] = {'sharpe': float(sharpe), 'mdd': float(mdd)}

        oos_results[label] = s_results

        s1_sharpe = s_results.get('S1: 8.63/VIX on 0050.TW', {}).get('sharpe', 0)
        s2_sharpe = s_results.get('S2: 8.63/VIX on TX Full-Day', {}).get('sharpe', 0)
        s4_sharpe = s_results.get('S4: Split VT (Day+Night)', {}).get('sharpe', 0)

        if s2_sharpe > s1_sharpe:
            s2_wins += 1
        if s4_sharpe > s1_sharpe:
            s4_wins += 1

        print(f"\n  {label} ({mask.sum()} days):")
        for sname in strategies:
            if sname in s_results:
                print(f"    {sname}: Sharpe={s_results[sname]['sharpe']:.3f}, MDD={s_results[sname]['mdd']*100:.1f}%")

    total_periods = len(oos_results)
    print(f"\n  Summary: S2 beats S1 in {s2_wins}/{total_periods} periods")
    print(f"           S4 beats S1 in {s4_wins}/{total_periods} periods")

    # ============================================================
    # Step 11: Futures basis analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("Step 11: Futures Basis / Roll Analysis")
    print("=" * 70)

    # Rolling basis: TX cumulative return vs 0050.TW cumulative return
    cum_tx = (1 + merged_full['full_day_ret']).cumprod()
    cum_tw = (1 + merged_full['tw50_ret']).cumprod()
    rolling_basis = (cum_tx / cum_tw - 1)

    print(f"\n  Cumulative basis drift (TX/0050 - 1):")
    print(f"    Final: {rolling_basis.iloc[-1]*100:.2f}%")
    print(f"    Mean:  {rolling_basis.mean()*100:.2f}%")
    print(f"    Std:   {rolling_basis.std()*100:.2f}%")
    print(f"    Min:   {rolling_basis.min()*100:.2f}%")
    print(f"    Max:   {rolling_basis.max()*100:.2f}%")

    # Annual basis decay
    print(f"\n  Annual basis analysis:")
    for year in range(2018, 2027):
        mask = merged_full.index.year == year
        if mask.sum() > 50:
            tx_ann = merged_full.loc[mask, 'full_day_ret'].sum() * 100
            tw_ann = merged_full.loc[mask, 'tw50_ret'].sum() * 100
            diff = tx_ann - tw_ann
            print(f"    {year}: TX={tx_ann:.2f}%, 0050={tw_ann:.2f}%, Diff={diff:.2f}%")

    # ============================================================
    # Step 12: Summary and Conclusion
    # ============================================================
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)

    s1_sharpe = perf_results['S1: 8.63/VIX on 0050.TW']['sharpe']
    s2_sharpe = perf_results['S2: 8.63/VIX on TX Full-Day']['sharpe']
    s4_sharpe = perf_results['S4: Split VT (Day+Night)']['sharpe']
    s1_mdd = perf_results['S1: 8.63/VIX on 0050.TW']['mdd']
    s2_mdd = perf_results['S2: 8.63/VIX on TX Full-Day']['mdd']
    s4_mdd = perf_results['S4: Split VT (Day+Night)']['mdd']

    print(f"\n  Key question: Does TX futures improve 8.63/VIX VT strategy?")
    print(f"\n  Sharpe comparison:")
    print(f"    S1 (0050.TW):    {s1_sharpe:.3f}")
    print(f"    S2 (TX Full):    {s2_sharpe:.3f} ({'↑' if s2_sharpe > s1_sharpe else '↓'} {abs(s2_sharpe-s1_sharpe):.3f})")
    print(f"    S4 (Split VT):   {s4_sharpe:.3f} ({'↑' if s4_sharpe > s1_sharpe else '↓'} {abs(s4_sharpe-s1_sharpe):.3f})")
    print(f"\n  MDD comparison:")
    print(f"    S1: {s1_mdd*100:.1f}%")
    print(f"    S2: {s2_mdd*100:.1f}%")
    print(f"    S4: {s4_mdd*100:.1f}%")

    s2_vs_s1_dm = dm_results.get('S2 vs S1', {})
    print(f"\n  Statistical significance (S2 vs S1):")
    print(f"    DM stat: {s2_vs_s1_dm.get('dm_stat', 'N/A')}")
    print(f"    p-value: {s2_vs_s1_dm.get('p_value', 'N/A')}")
    print(f"    Harvey t>3.0: {s2_vs_s1_dm.get('harvey_pass', 'N/A')}")

    # ============================================================
    # Save results
    # ============================================================
    results = {
        'experiment_id': 'K844',
        'title': 'TX Futures VT vs 0050.TW Stock VT',
        'date': datetime.now().strftime('%Y-%m-%d'),
        'data_source': 'TAIFEX TX tick data + yfinance (^VIX, 0050.TW)',
        'period': f"{merged_full.index[0].date()} to {merged_full.index[-1].date()}",
        'n_days': int(len(merged_full)),
        'return_decomposition': {
            'night_session_annualized_bp': float(night_mean * 10000),
            'gap_annualized_bp': float(gap_mean * 10000),
            'day_session_annualized_bp': float(day_mean * 10000),
            'full_day_annualized_bp': float(full_mean * 10000),
            'tw50_c2c_annualized_bp': float(tw50_mean * 10000),
            'night_pct_of_full': float(night_pct),
            'gap_pct_of_full': float(gap_pct),
            'day_pct_of_full': float(day_pct),
        },
        'correlation': {
            'tx_c2c_vs_tw50_c2c': float(corr_c2c),
            'tx_fullday_vs_tw50_c2c': float(corr_full),
        },
        'performance': perf_results,
        'dm_tests': dm_results,
        'cross_oos': oos_results,
        'cross_oos_summary': {
            's2_beats_s1': f"{s2_wins}/{total_periods}",
            's4_beats_s1': f"{s4_wins}/{total_periods}",
        },
        'tx_cost_analysis': {
            'total_tc_s1_stock_pct': float(tc_s1 * 100),
            'total_tc_s2_futures_pct': float(tc_s2 * 100),
            'annualized_saving_bps': float((tc_s1 - tc_s2) / years * 10000),
        },
        'basis_analysis': {
            'final_cumulative_drift_pct': float(rolling_basis.iloc[-1] * 100),
            'annualized_drift_pct': float(rolling_basis.iloc[-1] / years * 100),
        },
        'conclusion': '',
    }

    # Build conclusion string
    if s2_sharpe > s1_sharpe and s2_vs_s1_dm.get('harvey_pass', False):
        conclusion = f"TX futures SIGNIFICANTLY improve VT strategy. S2 Sharpe {s2_sharpe:.3f} vs S1 {s1_sharpe:.3f}, DM Harvey PASS."
    elif s2_sharpe > s1_sharpe:
        conclusion = f"TX futures improve VT strategy but NOT statistically significant. S2 Sharpe {s2_sharpe:.3f} vs S1 {s1_sharpe:.3f}, DM Harvey FAIL."
    else:
        conclusion = f"TX futures do NOT improve VT strategy. S2 Sharpe {s2_sharpe:.3f} vs S1 {s1_sharpe:.3f}."

    # Add basis warning
    ann_drift = rolling_basis.iloc[-1] / years * 100
    if abs(ann_drift) > 1.0:
        conclusion += f" WARNING: Significant basis drift ({ann_drift:.1f}%/yr) — roll costs or basis decay may erode futures advantage."

    # Add TX cost advantage
    tc_saving = (tc_s1 - tc_s2) / years * 10000
    conclusion += f" TX cost advantage: {tc_saving:.0f} bp/yr."

    results['conclusion'] = conclusion
    print(f"\n  {conclusion}")

    # Save
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               'k844_futures_vs_stock_vt_results.json')
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {output_path}")

    print("\n" + "=" * 70)
    print("K844 COMPLETE")
    print("=" * 70)
