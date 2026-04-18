#!/usr/bin/env python3
"""
K521: SPY 2-Day Momentum Overnight Gap — Artifact or Real?
==========================================================
[提出: 用戶, 執行: Claude]

Background:
  K520 sensitivity analysis found SPY 2-day momentum conditioning gives
  Sharpe=3.549 vs 1-day Sharpe=1.079 — a 3.3x difference.
  This is suspicious and must be thoroughly investigated before trusting.

Investigation plan:
  1. Timezone alignment verification (SPY close vs TW open)
  2. Data alignment validation (merge_asof correctness)
  3. Manual day-by-day signal verification (first 20 days)
  4. N-day momentum monotonicity (1d, 2d, 3d, 5d, 10d, 21d)
  5. Sub-period stability (5 sub-periods)
  6. Reverse causality test (TW gap → SPY next day)
  7. Shuffled signal test (random permutation baseline)
  8. pct_change(2) semantics check — is it truly look-ahead free?

Key concern:
  spy_close.pct_change(2) on date T uses close[T] and close[T-2].
  For Taiwan date T, merge_asof(direction='backward') maps to the
  most recent SPY date <= T. If SPY traded on the same calendar date T,
  then pct_change(2) uses SPY close on day T — which happens at 4PM ET.
  But Taiwan already opened at 9AM TST (= 8PM ET previous day).
  So SPY(T) close is AFTER Taiwan(T) open → LOOK-AHEAD BIAS!

  For 1-day return (pct_change(1)):
    SPY(T) return = close(T)/close(T-1) - 1
    Also uses SPY close on T → same look-ahead problem?
    But K519/K516 used merge_asof to get the PREVIOUS US trading day.
    So spy_ret_prev for TW date T should be SPY return on T-1 (or earlier).

  For 2-day return (pct_change(2)):
    SPY(T) 2d_ret = close(T)/close(T-2) - 1
    If merge_asof maps TW(T) → SPY(T), then we're using SPY close(T)
    which is not yet known when Taiwan(T) opens!

  This is likely the bug: pct_change(2) on spy_close, then merge_asof
  backward picks up SPY(T) 2d return for TW(T), but SPY(T) close
  happens AFTER TW(T) open.

  FIX: Shift SPY signals by 1 day before merge_asof, or use
  spy_ret.rolling(2).sum() on already-lagged returns.

References:
  - K520: Sensitivity analysis showing Sharpe 3.549 for 2-day momentum
  - K519: Premium Futures Strategy — S2 VT-Sized Overnight, Sharpe 1.079
  - K516: Overnight Gap Futures — Sharpe 0.93 at 5bp TX
  - Lou, Polk, Skouras (2019): A Tug of War, JFE

Data: yfinance — 0050.TW, SPY, ^VIX — 2010-2025
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K521: SPY 2-Day Momentum — Artifact or Real?")
print("=" * 70)

# ============================================================
# 1. Data Collection
# ============================================================
print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

for df_raw in [tw50, spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

print(f"  0050.TW: {len(tw50)} days")
print(f"  SPY:     {len(spy)} days")
print(f"  VIX:     {len(vix)} days")

# ============================================================
# 2. Compute Returns
# ============================================================
print("\n[2] Computing returns...")

tw_close = tw50['Close'].copy()
tw_open = tw50['Open'].copy()

valid_mask = (tw_close > 0) & (tw_open > 0) & tw_close.notna() & tw_open.notna()
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]

# Gap return: (today's open - yesterday's close) / yesterday's close
gap_ret = (tw_open - tw_close.shift(1)) / tw_close.shift(1)
gap_ret = gap_ret.dropna()

c2c_ret = tw_close.pct_change().dropna()

for s in [gap_ret, c2c_ret]:
    outlier = s.abs() > 0.15
    if outlier.sum() > 0:
        s.drop(s[outlier].index, inplace=True)

spy_close = spy['Close'].copy()
spy_ret = spy_close.pct_change().dropna()
vix_close = vix['Close'].copy()


def normalize_dt(s):
    """Normalize datetime index/column to datetime64[ns] for merge_asof compatibility."""
    if hasattr(s, 'dt'):
        return s.astype('datetime64[ns]')
    return s


# ============================================================
# 3. CRITICAL: Timezone Alignment Analysis
# ============================================================
print("\n[3] CRITICAL: Timezone Alignment Analysis")
print("=" * 70)

print("""
  Timeline (for a given calendar date T):

  SPY close T-1: 4:00 PM ET = next day 5:00 AM TST (= T 05:00 TST)
  Taiwan open T: 9:00 AM TST
  Taiwan close T: 1:30 PM TST
  SPY open T:     9:30 AM ET = T 10:30 PM TST (AFTER TW close)
  SPY close T:    4:00 PM ET = T+1 5:00 AM TST (AFTER TW close)

  So for Taiwan trading day T:
    - SPY close T-1 is available (happened ~4 hours before TW open)
    - SPY close T is NOT available (happens ~9 hours AFTER TW close)

  For gap_ret on TW date T:
    - Taiwan open T is at 9 AM TST
    - We need signals available BEFORE 9 AM TST on day T
    - SPY close on T-1 (5 AM TST on day T) ✓ available
    - SPY close on T (5 AM TST on day T+1) ✗ NOT available
""")

# ============================================================
# 4. Check K520's merge_asof behavior
# ============================================================
print("\n[4] Checking K520's merge_asof behavior...")
print("=" * 70)

# K520 method: spy_close.pct_change(2) → merge_asof backward
# This means for TW date T, we get the most recent SPY 2d return
# where SPY date <= T.

# But SPY trades on date T AFTER TW opens on date T!
# When SPY date == TW date (both trade on same calendar day),
# merge_asof picks up SPY(T) which includes SPY close on day T.
# SPY close T = 4PM ET = 5AM TST day T+1 → FUTURE INFO for TW day T!

# Let's verify this empirically
spy_2d_raw = spy_close.pct_change(2).dropna()

# Create merge frames
df = pd.DataFrame(index=tw50.index)
df['gap_ret'] = gap_ret
df['tw_close'] = tw_close
df['tw_open'] = tw_open

spy_2d_reset = spy_2d_raw.reset_index()
spy_2d_reset.columns = ['spy_date', 'spy_2d']
spy_2d_reset['spy_date'] = pd.to_datetime(spy_2d_reset['spy_date']).astype('datetime64[ns]')
spy_2d_reset = spy_2d_reset.dropna().sort_values('spy_date')

df_reset = df.reset_index()
date_col = [c for c in df_reset.columns if 'date' in c.lower() or 'Date' in c or c == 'Price']
if date_col:
    date_col = date_col[0]
else:
    date_col = df_reset.columns[0]
if date_col != 'tw_date':
    df_reset.rename(columns={date_col: 'tw_date'}, inplace=True)
df_reset['tw_date'] = pd.to_datetime(df_reset['tw_date']).astype('datetime64[ns]')
df_for_merge = df_reset[['tw_date']].sort_values('tw_date')

# K520-style merge (potentially buggy)
merged_buggy = pd.merge_asof(df_for_merge, spy_2d_reset,
                              left_on='tw_date', right_on='spy_date',
                              direction='backward')
merged_buggy = merged_buggy.set_index('tw_date')

# Check: how often does spy_date == tw_date?
# This would mean we're using SPY data from the same calendar day,
# which is look-ahead for Taiwan!
n_same_day = (merged_buggy.index == merged_buggy['spy_date']).sum()
n_total = len(merged_buggy.dropna())
pct_same = n_same_day / n_total * 100 if n_total > 0 else 0

print(f"  Total merged rows: {n_total}")
print(f"  Same-day matches (SPY date == TW date): {n_same_day} ({pct_same:.1f}%)")
print(f"  → If same-day > 0, look-ahead bias exists for those days!")

# Show first 20 examples of same-day matches
same_day_mask = merged_buggy.index == merged_buggy['spy_date']
same_day_examples = merged_buggy[same_day_mask].head(20)
print(f"\n  First 20 same-day matches (LOOK-AHEAD):")
print(f"  {'TW Date':<12} {'SPY Date':<12} {'SPY 2d ret':>12}")
for idx, row in same_day_examples.iterrows():
    print(f"  {idx.strftime('%Y-%m-%d'):<12} "
          f"{row['spy_date'].strftime('%Y-%m-%d') if pd.notna(row['spy_date']) else 'NaT':<12} "
          f"{row['spy_2d']:>12.6f}")

# ============================================================
# 5. CORRECT method: shift SPY data by 1 day
# ============================================================
print("\n\n[5] CORRECT method: proper lag to avoid look-ahead")
print("=" * 70)

# Method A: Shift spy_close by 1 before computing pct_change(2)
# This ensures we only use SPY closes from T-1 and earlier
# spy_close.shift(1).pct_change(2) uses close[T-1] and close[T-3]

# Method B: Compute on spy_ret (already 1-day returns), then rolling sum
# spy_ret is close[T]/close[T-1]-1, available after SPY T close
# For TW date T+1, spy_ret[T] is available. So we need previous day's spy_ret.
# spy_ret_prev = merge_asof(backward) of spy_ret → gives spy_ret on or before TW date
# Then spy_2d_correct = spy_ret_prev.rolling(2).sum() → uses ret[T-1] + ret[T-2]

# Method C (cleanest): Just shift the SPY data by 1 day before merge_asof
# For each SPY date T, assign the value to date T+1
# Then merge_asof backward will map TW(T) → SPY(T-1) at most

# Let's implement Method C
spy_2d_shifted = spy_2d_raw.copy()
spy_2d_shifted.index = spy_2d_shifted.index + pd.Timedelta(days=1)
spy_2d_shifted_reset = spy_2d_shifted.reset_index()
spy_2d_shifted_reset.columns = ['spy_date_shifted', 'spy_2d_correct']
spy_2d_shifted_reset['spy_date_shifted'] = pd.to_datetime(spy_2d_shifted_reset['spy_date_shifted']).astype('datetime64[ns]')
spy_2d_shifted_reset = spy_2d_shifted_reset.dropna().sort_values('spy_date_shifted')

merged_correct = pd.merge_asof(df_for_merge, spy_2d_shifted_reset,
                                left_on='tw_date', right_on='spy_date_shifted',
                                direction='backward')
merged_correct = merged_correct.set_index('tw_date')

# Also do the same for 1-day return to verify K519's method was correct
spy_1d_reset = spy_ret.reset_index()
spy_1d_reset.columns = ['spy_date', 'spy_1d']
spy_1d_reset['spy_date'] = pd.to_datetime(spy_1d_reset['spy_date']).astype('datetime64[ns]')
spy_1d_reset = spy_1d_reset.dropna().sort_values('spy_date')

merged_1d = pd.merge_asof(df_for_merge, spy_1d_reset,
                           left_on='tw_date', right_on='spy_date',
                           direction='backward')
merged_1d = merged_1d.set_index('tw_date')

n_same_1d = (merged_1d.index == merged_1d['spy_date']).sum()
n_total_1d = len(merged_1d.dropna())
pct_same_1d = n_same_1d / n_total_1d * 100 if n_total_1d > 0 else 0

print(f"  1-day SPY ret (K519 method): same-day matches = {n_same_1d} ({pct_same_1d:.1f}%)")
print(f"  → K519's 1-day signal ALSO has look-ahead if same-day > 0!")

# Correct 1-day too
spy_1d_shifted = spy_ret.copy()
spy_1d_shifted.index = spy_1d_shifted.index + pd.Timedelta(days=1)
spy_1d_shifted_reset = spy_1d_shifted.reset_index()
spy_1d_shifted_reset.columns = ['spy_date_shifted', 'spy_1d_correct']
spy_1d_shifted_reset['spy_date_shifted'] = pd.to_datetime(spy_1d_shifted_reset['spy_date_shifted']).astype('datetime64[ns]')
spy_1d_shifted_reset = spy_1d_shifted_reset.dropna().sort_values('spy_date_shifted')

merged_1d_correct = pd.merge_asof(df_for_merge, spy_1d_shifted_reset,
                                    left_on='tw_date', right_on='spy_date_shifted',
                                    direction='backward')
merged_1d_correct = merged_1d_correct.set_index('tw_date')

# Build the full analysis dataframe
df['spy_2d_buggy'] = merged_buggy['spy_2d']
df['spy_2d_correct'] = merged_correct['spy_2d_correct']
df['spy_1d_buggy'] = merged_1d['spy_1d']
df['spy_1d_correct'] = merged_1d_correct['spy_1d_correct']

# VIX
vix_reset = vix_close.reset_index()
if isinstance(vix_reset.columns, pd.MultiIndex):
    vix_reset.columns = ['_'.join(str(c) for c in col).strip('_') for col in vix_reset.columns]
vix_reset.columns = ['vix_date', 'vix_close']
vix_reset['vix_date'] = pd.to_datetime(vix_reset['vix_date']).astype('datetime64[ns]')
vix_reset = vix_reset.dropna().sort_values('vix_date')

merged_vix = pd.merge_asof(df_for_merge, vix_reset,
                            left_on='tw_date', right_on='vix_date',
                            direction='backward')
df['vix_prev'] = merged_vix.set_index('tw_date')['vix_close']

df_clean = df.dropna(subset=['gap_ret', 'vix_prev', 'spy_2d_buggy', 'spy_2d_correct',
                              'spy_1d_buggy', 'spy_1d_correct'])
print(f"  Clean dataset: {len(df_clean)} trading days")
print(f"  Period: {df_clean.index[0].strftime('%Y-%m-%d')} to {df_clean.index[-1].strftime('%Y-%m-%d')}")

# Check correlation between buggy and correct signals
corr_2d = df_clean['spy_2d_buggy'].corr(df_clean['spy_2d_correct'])
corr_1d = df_clean['spy_1d_buggy'].corr(df_clean['spy_1d_correct'])
print(f"\n  Correlation (buggy vs correct):")
print(f"    1-day: {corr_1d:.4f}")
print(f"    2-day: {corr_2d:.4f}")

# How often do signals disagree?
disagree_1d = ((df_clean['spy_1d_buggy'] > 0) != (df_clean['spy_1d_correct'] > 0)).mean()
disagree_2d = ((df_clean['spy_2d_buggy'] > 0) != (df_clean['spy_2d_correct'] > 0)).mean()
print(f"\n  Signal disagreement rate (buggy vs correct):")
print(f"    1-day: {disagree_1d*100:.1f}%")
print(f"    2-day: {disagree_2d*100:.1f}%")

# ============================================================
# 6. Manual verification: print first 30 days
# ============================================================
print("\n\n[6] Manual verification: first 30 aligned days")
print("=" * 70)

sample = df_clean.head(30)
print(f"  {'TW Date':<12} {'Gap%':>7} {'1d Bug':>8} {'1d Fix':>8} {'2d Bug':>8} {'2d Fix':>8} {'Disagr':>7}")
for idx, row in sample.iterrows():
    d1_agree = "✓" if (row['spy_1d_buggy'] > 0) == (row['spy_1d_correct'] > 0) else "✗"
    d2_agree = "✓" if (row['spy_2d_buggy'] > 0) == (row['spy_2d_correct'] > 0) else "✗"
    print(f"  {idx.strftime('%Y-%m-%d'):<12} "
          f"{row['gap_ret']*100:>7.3f} "
          f"{row['spy_1d_buggy']*100:>7.3f}% "
          f"{row['spy_1d_correct']*100:>7.3f}% "
          f"{row['spy_2d_buggy']*100:>7.3f}% "
          f"{row['spy_2d_correct']*100:>7.3f}% "
          f"{d1_agree}{d2_agree}")

# ============================================================
# 7. Strategy comparison: Buggy vs Correct
# ============================================================
print("\n\n[7] Strategy comparison: Buggy (K520) vs Correct signals")
print("=" * 70)

N_TOTAL = len(df_clean)

def compute_metrics(returns, n_total_days=None):
    """Compute strategy metrics."""
    returns = returns.dropna()
    n = len(returns)
    if n < 30:
        return None

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    mdd = ((cum - peak) / peak).min()
    total_ret = cum.iloc[-1] - 1

    years = n / 252
    cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 and cum.iloc[-1] > 0 else -1

    trading_days = returns[returns != 0]
    if len(trading_days) > 10:
        t_stat, p_val = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat, p_val = 0.0, 1.0

    win_rate = (trading_days > 0).mean() if len(trading_days) > 0 else 0
    n_active = (returns != 0).sum()
    exposure = n_active / n_total_days if n_total_days else n_active / n

    return {
        'n_days': n,
        'n_active': int(n_active),
        'exposure_pct': round(float(exposure * 100), 1),
        'ann_return_pct': round(float(ann_ret * 100), 2),
        'ann_vol_pct': round(float(ann_vol * 100), 2),
        'sharpe': round(float(sharpe), 3),
        'cagr_pct': round(float(cagr * 100), 2),
        'total_return_pct': round(float(total_ret * 100), 2),
        'mdd_pct': round(float(mdd * 100), 2),
        't_stat': round(float(t_stat), 3),
        'p_val': round(float(p_val), 4),
        'win_rate_pct': round(float(win_rate * 100), 1),
    }


def run_strategy(data, tx_bps, vix_thresh, signal_col, k_val=8.63, pos_cap=2.0):
    """Run VT-sized overnight strategy."""
    tx_cost = tx_bps / 10000.0
    vt_size = (k_val / data['vix_prev']).clip(upper=pos_cap)

    if signal_col is not None and vix_thresh is not None:
        sig_binary = ((data[signal_col] > 0) & (data['vix_prev'] < vix_thresh)).astype(float)
    elif signal_col is not None:
        sig_binary = (data[signal_col] > 0).astype(float)
    elif vix_thresh is not None:
        sig_binary = (data['vix_prev'] < vix_thresh).astype(float)
    else:
        sig_binary = pd.Series(1.0, index=data.index)

    sig = vt_size * sig_binary
    gross = data['gap_ret'] * sig
    net = gross - tx_cost * sig
    return net


OOS_PERIODS = [
    ('2013-01-01', '2015-12-31'),
    ('2016-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2021-01-01', '2023-06-30'),
    ('2023-07-01', '2025-12-31'),
]


def cross_oos_test(data, tx_bps, vix_thresh, signal_col, k_val=8.63, pos_cap=2.0):
    """Cross-OOS validation."""
    wins = 0
    sharpes = []
    for start, end in OOS_PERIODS:
        mask = (data.index >= start) & (data.index <= end)
        d = data[mask]
        if len(d) < 30:
            sharpes.append(0)
            continue
        net = run_strategy(d, tx_bps, vix_thresh, signal_col, k_val, pos_cap)
        m = compute_metrics(net, n_total_days=len(d))
        if m and m['sharpe'] > 0:
            wins += 1
        sharpes.append(m['sharpe'] if m else 0)
    return wins, sharpes


strategies = {
    '1d_buggy (K519/K520)': 'spy_1d_buggy',
    '1d_correct (lag-fixed)': 'spy_1d_correct',
    '2d_buggy (K520)': 'spy_2d_buggy',
    '2d_correct (lag-fixed)': 'spy_2d_correct',
    'No SPY signal': None,
}

comparison_results = {}
print(f"\n  {'Strategy':<28} {'Sharpe':>7} {'AnnRet%':>8} {'MDD%':>7} {'t-stat':>7} {'OOS':>5} {'Exp%':>5}")
print(f"  {'-'*28} {'-'*7} {'-'*8} {'-'*7} {'-'*7} {'-'*5} {'-'*5}")

for name, col in strategies.items():
    net = run_strategy(df_clean, tx_bps=5, vix_thresh=25, signal_col=col)
    m = compute_metrics(net, n_total_days=N_TOTAL)
    wins, oos_sharpes = cross_oos_test(df_clean, 5, 25, col)

    comparison_results[name] = {
        'signal_col': col if col else 'none',
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'ann_vol_pct': m['ann_vol_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
        'exposure_pct': m['exposure_pct'] if m else 0,
        'win_rate_pct': m['win_rate_pct'] if m else 0,
    }
    print(f"  {name:<28} {m['sharpe']:>7.3f} {m['ann_return_pct']:>7.2f}% "
          f"{m['mdd_pct']:>6.2f}% {m['t_stat']:>6.3f} {wins}/5 {m['exposure_pct']:>5.1f}")

# ============================================================
# 8. N-day momentum sweep (correct lag)
# ============================================================
print("\n\n[8] N-day momentum sweep (all with correct lag)")
print("=" * 70)

nday_results = []
n_days_list = [1, 2, 3, 5, 10, 21]

for nd in n_days_list:
    # Compute N-day return on SPY
    spy_nd = spy_close.pct_change(nd).dropna()
    # Shift by 1 day to avoid look-ahead
    spy_nd_shifted = spy_nd.copy()
    spy_nd_shifted.index = spy_nd_shifted.index + pd.Timedelta(days=1)
    spy_nd_reset = spy_nd_shifted.reset_index()
    spy_nd_reset.columns = ['spy_date', f'spy_{nd}d']
    spy_nd_reset['spy_date'] = pd.to_datetime(spy_nd_reset['spy_date']).astype('datetime64[ns]')
    spy_nd_reset = spy_nd_reset.dropna().sort_values('spy_date')

    merged_nd = pd.merge_asof(df_for_merge, spy_nd_reset,
                               left_on='tw_date', right_on='spy_date',
                               direction='backward')
    col_name = f'spy_{nd}d_correct'
    df_clean[col_name] = merged_nd.set_index('tw_date')[f'spy_{nd}d']

    # Run strategy
    net = run_strategy(df_clean.dropna(subset=[col_name, 'gap_ret', 'vix_prev']),
                       tx_bps=5, vix_thresh=25, signal_col=col_name)
    m = compute_metrics(net, n_total_days=N_TOTAL)
    wins, oos_sharpes = cross_oos_test(
        df_clean.dropna(subset=[col_name, 'gap_ret', 'vix_prev']),
        5, 25, col_name)

    entry = {
        'n_days': nd,
        'sharpe': m['sharpe'] if m else 0,
        'ann_return_pct': m['ann_return_pct'] if m else 0,
        'mdd_pct': m['mdd_pct'] if m else 0,
        't_stat': m['t_stat'] if m else 0,
        'cross_oos_wins': wins,
        'oos_sharpes': [round(s, 3) for s in oos_sharpes],
        'exposure_pct': m['exposure_pct'] if m else 0,
    }
    nday_results.append(entry)
    print(f"  {nd:>2}d: Sharpe={entry['sharpe']:>6.3f}, AnnRet={entry['ann_return_pct']:>6.2f}%, "
          f"MDD={entry['mdd_pct']:>6.2f}%, t={entry['t_stat']:>5.3f}, OOS={wins}/5, "
          f"exposure={entry['exposure_pct']:.1f}%")

# Check monotonicity
sharpes_nday = [r['sharpe'] for r in nday_results]
is_monotonic = all(sharpes_nday[i] >= sharpes_nday[i+1] for i in range(len(sharpes_nday)-1)) or \
               all(sharpes_nday[i] <= sharpes_nday[i+1] for i in range(len(sharpes_nday)-1))
print(f"\n  Monotonic pattern? {'Yes' if is_monotonic else 'No'}")
print(f"  Sharpe pattern: {' → '.join(f'{s:.3f}' for s in sharpes_nday)}")

# ============================================================
# 9. Sub-period stability (correct 2d signal)
# ============================================================
print("\n\n[9] Sub-period stability (correct 2d vs 1d)")
print("=" * 70)

print(f"  {'Period':<22} {'1d_correct':>12} {'2d_correct':>12} {'No Signal':>12}")

for start, end in OOS_PERIODS:
    mask = (df_clean.index >= start) & (df_clean.index <= end)
    d = df_clean[mask]
    if len(d) < 30:
        continue

    net_1d = run_strategy(d, 5, 25, 'spy_1d_correct')
    m_1d = compute_metrics(net_1d, n_total_days=len(d))

    net_2d = run_strategy(d, 5, 25, 'spy_2d_correct')
    m_2d = compute_metrics(net_2d, n_total_days=len(d))

    net_none = run_strategy(d, 5, 25, None)
    m_none = compute_metrics(net_none, n_total_days=len(d))

    s_1d = m_1d['sharpe'] if m_1d else 0
    s_2d = m_2d['sharpe'] if m_2d else 0
    s_none = m_none['sharpe'] if m_none else 0

    print(f"  {start}~{end} {s_1d:>12.3f} {s_2d:>12.3f} {s_none:>12.3f}")

# ============================================================
# 10. Reverse causality test
# ============================================================
print("\n\n[10] Reverse causality test: TW gap → SPY next day")
print("=" * 70)

# If TW gap > 0 on day T, does SPY go up on day T?
# This would be a "reverse" effect (Taiwan leading US)
tw_gap_signal = (df_clean['gap_ret'] > 0).astype(float)

# SPY return on the same day (after TW close) — use spy_1d_buggy which is same-day
spy_same_day = df_clean['spy_1d_buggy']

# Correlation
corr_reverse = tw_gap_signal.corr(spy_same_day)
print(f"  Correlation(TW gap > 0, SPY same day return): {corr_reverse:.4f}")

# Mean SPY return conditional on TW gap direction
spy_when_tw_up = spy_same_day[tw_gap_signal == 1].mean() * 100
spy_when_tw_down = spy_same_day[tw_gap_signal == 0].mean() * 100
print(f"  Mean SPY return when TW gap > 0: {spy_when_tw_up:.4f}%")
print(f"  Mean SPY return when TW gap <= 0: {spy_when_tw_down:.4f}%")
print(f"  Difference: {spy_when_tw_up - spy_when_tw_down:.4f}%")
print(f"  → If this is large, there's bidirectional correlation (not look-ahead)")

# ============================================================
# 11. Shuffled signal test (correct 2d)
# ============================================================
print("\n\n[11] Shuffled signal test (randomize 2d_correct signal)")
print("=" * 70)

np.random.seed(42)
n_shuffles = 1000
shuffled_sharpes = []

signal_values = df_clean['spy_2d_correct'].values.copy()

for _ in range(n_shuffles):
    np.random.shuffle(signal_values)
    shuffled_sig = pd.Series(signal_values, index=df_clean.index)
    # Same strategy logic
    vt_size = (8.63 / df_clean['vix_prev']).clip(upper=2.0)
    sig_binary = ((shuffled_sig > 0) & (df_clean['vix_prev'] < 25)).astype(float)
    sig = vt_size * sig_binary
    gross = df_clean['gap_ret'] * sig
    net = gross - (5 / 10000.0) * sig
    net = net.dropna()
    if len(net) > 30:
        ann_ret = net.mean() * 252
        ann_vol = net.std() * np.sqrt(252)
        sh = ann_ret / ann_vol if ann_vol > 0 else 0
        shuffled_sharpes.append(sh)

actual_sharpe = comparison_results.get('2d_correct (lag-fixed)', {}).get('sharpe', 0)

shuffled_mean = np.mean(shuffled_sharpes)
shuffled_std = np.std(shuffled_sharpes)
shuffled_p95 = np.percentile(shuffled_sharpes, 95)
shuffled_p99 = np.percentile(shuffled_sharpes, 99)
z_score = (actual_sharpe - shuffled_mean) / shuffled_std if shuffled_std > 0 else 0

print(f"  Shuffled Sharpe: mean={shuffled_mean:.3f}, std={shuffled_std:.3f}")
print(f"  Shuffled 95th percentile: {shuffled_p95:.3f}")
print(f"  Shuffled 99th percentile: {shuffled_p99:.3f}")
print(f"  Actual Sharpe (2d correct): {actual_sharpe:.3f}")
print(f"  Z-score: {z_score:.2f}")
print(f"  → Signal {'beats random at 95% level' if actual_sharpe > shuffled_p95 else 'NOT significant vs random'}")

# ============================================================
# 12. Key diagnostic: what's the actual look-ahead boost?
# ============================================================
print("\n\n[12] Quantifying the look-ahead bias")
print("=" * 70)

buggy_2d_sharpe = comparison_results.get('2d_buggy (K520)', {}).get('sharpe', 0)
correct_2d_sharpe = comparison_results.get('2d_correct (lag-fixed)', {}).get('sharpe', 0)
buggy_1d_sharpe = comparison_results.get('1d_buggy (K519/K520)', {}).get('sharpe', 0)
correct_1d_sharpe = comparison_results.get('1d_correct (lag-fixed)', {}).get('sharpe', 0)

print(f"  1-day signal:")
print(f"    Buggy (K519/K520): Sharpe = {buggy_1d_sharpe:.3f}")
print(f"    Correct (lag-fix): Sharpe = {correct_1d_sharpe:.3f}")
print(f"    Difference:        {buggy_1d_sharpe - correct_1d_sharpe:+.3f}")
print(f"    → {'LOOK-AHEAD BIAS CONFIRMED' if buggy_1d_sharpe - correct_1d_sharpe > 0.1 else 'Minimal bias'}")

print(f"\n  2-day signal:")
print(f"    Buggy (K520):      Sharpe = {buggy_2d_sharpe:.3f}")
print(f"    Correct (lag-fix): Sharpe = {correct_2d_sharpe:.3f}")
print(f"    Difference:        {buggy_2d_sharpe - correct_2d_sharpe:+.3f}")
print(f"    → {'LOOK-AHEAD BIAS CONFIRMED' if buggy_2d_sharpe - correct_2d_sharpe > 0.3 else 'Minimal bias'}")

# ============================================================
# 13. IMPORTANT: Check if K519's original signal also had bias
# ============================================================
print("\n\n[13] K519 original signal audit")
print("=" * 70)

print(f"  K519 used: spy_close.pct_change().dropna() → merge_asof(backward)")
print(f"  This computes spy_ret[T] = close[T]/close[T-1] - 1")
print(f"  Then merge_asof maps TW date T → most recent SPY date <= T")
print(f"  If SPY traded on calendar date T, it picks up spy_ret[T]")
print(f"  But spy_ret[T] uses close[T] which is at 4PM ET = 5AM TST next day")
print(f"  → This IS look-ahead for Taiwan!")
print(f"")
print(f"  However, the bias is partial:")
print(f"    - SPY ret[T] = close[T]/close[T-1] - 1")
print(f"    - close[T-1] is known (~18 hours before TW(T) open)")
print(f"    - close[T] is NOT known (happens 9 hours after TW(T) close)")
print(f"    - So the signal contains one future data point (close[T])")
print(f"")
print(f"  The correct signal should use spy_ret[T-1] for Taiwan date T")
print(f"  (i.e., the return computed from close[T-2] to close[T-1])")
print(f"")
print(f"  Buggy 1d Sharpe: {buggy_1d_sharpe:.3f}")
print(f"  Correct 1d Sharpe: {correct_1d_sharpe:.3f}")

has_1d_bias = abs(buggy_1d_sharpe - correct_1d_sharpe) > 0.1
has_2d_bias = abs(buggy_2d_sharpe - correct_2d_sharpe) > 0.3

print(f"\n  1d look-ahead bias: {'YES' if has_1d_bias else 'MINIMAL'} (delta = {buggy_1d_sharpe - correct_1d_sharpe:+.3f})")
print(f"  2d look-ahead bias: {'YES' if has_2d_bias else 'MINIMAL'} (delta = {buggy_2d_sharpe - correct_2d_sharpe:+.3f})")

# ============================================================
# 14. Final Verdict
# ============================================================
print("\n\n" + "=" * 70)
print("FINAL VERDICT")
print("=" * 70)

verdict_items = []

if n_same_day > 0:
    verdict_items.append(f"LOOK-AHEAD CONFIRMED: {n_same_day} days ({pct_same:.1f}%) used same-day SPY data")
else:
    verdict_items.append("NO LOOK-AHEAD: All SPY data from previous trading days")

if has_2d_bias:
    verdict_items.append(f"2-DAY MOMENTUM ARTIFACT: Buggy Sharpe {buggy_2d_sharpe:.3f} → Correct {correct_2d_sharpe:.3f}")
else:
    verdict_items.append(f"2-day momentum real: Correct Sharpe = {correct_2d_sharpe:.3f}")

if has_1d_bias:
    verdict_items.append(f"1-DAY SIGNAL ALSO BIASED: Buggy {buggy_1d_sharpe:.3f} → Correct {correct_1d_sharpe:.3f}")
    verdict_items.append("→ K519 S2 Sharpe 1.079 is likely inflated — needs recomputation")
else:
    verdict_items.append(f"1-day signal robust: Correct Sharpe = {correct_1d_sharpe:.3f}")

for i, item in enumerate(verdict_items, 1):
    print(f"  {i}. {item}")

# Best correct strategy
correct_strats = {k: v for k, v in comparison_results.items() if 'correct' in k or 'No SPY' in k}
best_correct = max(correct_strats.items(), key=lambda x: x[1]['sharpe'])
print(f"\n  Best correct strategy: {best_correct[0]}")
print(f"    Sharpe: {best_correct[1]['sharpe']:.3f}")
print(f"    Ann Return: {best_correct[1]['ann_return_pct']:.2f}%")
print(f"    MDD: {best_correct[1]['mdd_pct']:.2f}%")
print(f"    Cross-OOS: {best_correct[1]['cross_oos_wins']}/5")

elapsed = time.time() - start_time
print(f"\n  Elapsed: {elapsed:.1f}s")

# ============================================================
# 15. Save results
# ============================================================
results = {
    'experiment_id': 'K521',
    'title': 'SPY 2-Day Momentum Overnight Gap — Artifact or Real?',
    'author': '[提出: 用戶, 執行: Claude]',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance — 0050.TW, SPY, ^VIX',
    'data_period': f"{df_clean.index[0].strftime('%Y-%m-%d')} to {df_clean.index[-1].strftime('%Y-%m-%d')}",
    'n_observations': len(df_clean),

    'look_ahead_diagnosis': {
        'same_day_matches': int(n_same_day),
        'same_day_pct': round(pct_same, 1),
        'explanation': (
            'merge_asof(direction=backward) maps TW date T to SPY date T '
            'when both markets trade on the same calendar day. '
            'But SPY closes at 4PM ET (= 5AM TST next day), which is '
            'AFTER Taiwan already traded. So using SPY(T) data for TW(T) '
            'is look-ahead bias.'
        ),
        '1d_has_bias': has_1d_bias,
        '2d_has_bias': has_2d_bias,
    },

    'signal_disagreement': {
        '1d_disagree_pct': round(disagree_1d * 100, 1),
        '2d_disagree_pct': round(disagree_2d * 100, 1),
    },

    'strategy_comparison': comparison_results,

    'nday_sweep_correct': nday_results,

    'shuffled_test': {
        'n_shuffles': n_shuffles,
        'shuffled_mean_sharpe': round(shuffled_mean, 3),
        'shuffled_std_sharpe': round(shuffled_std, 3),
        'shuffled_p95': round(shuffled_p95, 3),
        'shuffled_p99': round(shuffled_p99, 3),
        'actual_sharpe_2d_correct': round(actual_sharpe, 3),
        'z_score': round(z_score, 2),
        'significant_p95': actual_sharpe > shuffled_p95,
    },

    'reverse_causality': {
        'corr_tw_gap_spy_sameday': round(corr_reverse, 4),
        'spy_mean_when_tw_up': round(spy_when_tw_up, 4),
        'spy_mean_when_tw_down': round(spy_when_tw_down, 4),
    },

    'verdict': {
        'is_artifact': has_2d_bias,
        'look_ahead_confirmed': n_same_day > 0,
        '1d_signal_also_biased': has_1d_bias,
        'k519_needs_recomputation': has_1d_bias,
        'best_correct_strategy': best_correct[0],
        'best_correct_sharpe': best_correct[1]['sharpe'],
        'best_correct_oos': best_correct[1]['cross_oos_wins'],
        'items': verdict_items,
    },

    'implication_for_k519': (
        'K519 used spy_close.pct_change().dropna() → merge_asof(backward). '
        'This is the same look-ahead bug. K519 S2 Sharpe 1.079 is computed '
        'with future information. The correct Sharpe (with lag-fixed signal) '
        f'is {correct_1d_sharpe:.3f}. '
        'All overnight gap strategies using SPY signals need recomputation.'
    ) if has_1d_bias else (
        'K519 1-day signal has minimal bias after lag correction. '
        f'Correct Sharpe = {correct_1d_sharpe:.3f} vs buggy {buggy_1d_sharpe:.3f}.'
    ),

    'references': [
        'K520: Sensitivity analysis — SPY 2d momentum Sharpe=3.549 (buggy)',
        'K519: Premium Futures — S2 VT-Sized Overnight, Sharpe 1.079 (buggy)',
        'K516: Overnight Gap Futures — Sharpe 0.93 at 5bp TX',
        'Lou, Polk, Skouras (2019): A Tug of War, JFE',
    ],

    'elapsed_seconds': round(elapsed, 1),
}

output_path = 'experiments/k521/k521_2day_momentum_check_results.json'
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
