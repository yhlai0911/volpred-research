#!/usr/bin/env python3
"""
K521 Supplement: Verify the Sharpe 4.445 — is VT sizing inflating?
===================================================================
The lag-corrected 1d signal shows Sharpe 4.445 which is suspiciously high.
This supplement tests:
1. Binary signal (no VT sizing) — is the alpha real?
2. Simple equal-weight (no VIX filter) — isolating the signal
3. Day-by-day return distribution
4. Year-by-year breakdown
5. Check if VT amplification explains the high Sharpe
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K521 Supplement: Verify Sharpe 4.445 — VT sizing effect?")
print("=" * 70)

# Data download
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

for df_raw in [tw50, spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

tw_close = tw50['Close'].copy()
tw_open = tw50['Open'].copy()
valid_mask = (tw_close > 0) & (tw_open > 0) & tw_close.notna() & tw_open.notna()
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]

gap_ret = (tw_open - tw_close.shift(1)) / tw_close.shift(1)
gap_ret = gap_ret.dropna()
outlier = gap_ret.abs() > 0.15
if outlier.sum() > 0:
    gap_ret.drop(gap_ret[outlier].index, inplace=True)

spy_close = spy['Close'].copy()
spy_ret = spy_close.pct_change().dropna()
vix_close = vix['Close'].copy()

# Build dataframe
df = pd.DataFrame(index=tw50.index)
df['gap_ret'] = gap_ret
df['tw_close'] = tw_close
df['tw_open'] = tw_open

# CORRECT lag: shift SPY by 1 day before merge
spy_1d_shifted = spy_ret.copy()
spy_1d_shifted.index = spy_1d_shifted.index + pd.Timedelta(days=1)
spy_1d_shifted_reset = spy_1d_shifted.reset_index()
spy_1d_shifted_reset.columns = ['spy_date', 'spy_1d_correct']
spy_1d_shifted_reset['spy_date'] = pd.to_datetime(spy_1d_shifted_reset['spy_date']).astype('datetime64[ns]')
spy_1d_shifted_reset = spy_1d_shifted_reset.dropna().sort_values('spy_date')

# BUGGY (original K519): no shift
spy_1d_buggy_reset = spy_ret.reset_index()
spy_1d_buggy_reset.columns = ['spy_date', 'spy_1d_buggy']
spy_1d_buggy_reset['spy_date'] = pd.to_datetime(spy_1d_buggy_reset['spy_date']).astype('datetime64[ns]')
spy_1d_buggy_reset = spy_1d_buggy_reset.dropna().sort_values('spy_date')

df_reset = df.reset_index()
date_col = [c for c in df_reset.columns if 'date' in c.lower() or 'Date' in c or c == 'Price']
date_col = date_col[0] if date_col else df_reset.columns[0]
if date_col != 'tw_date':
    df_reset.rename(columns={date_col: 'tw_date'}, inplace=True)
df_reset['tw_date'] = pd.to_datetime(df_reset['tw_date']).astype('datetime64[ns]')
df_for_merge = df_reset[['tw_date']].sort_values('tw_date')

# Merge correct
merged_correct = pd.merge_asof(df_for_merge, spy_1d_shifted_reset,
                                left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_1d_correct'] = merged_correct.set_index('tw_date')['spy_1d_correct']

# Merge buggy
merged_buggy = pd.merge_asof(df_for_merge, spy_1d_buggy_reset,
                              left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_1d_buggy'] = merged_buggy.set_index('tw_date')['spy_1d_buggy']

# VIX
vix_reset = vix_close.reset_index()
if isinstance(vix_reset.columns, pd.MultiIndex):
    vix_reset.columns = ['_'.join(str(c) for c in col).strip('_') for col in vix_reset.columns]
vix_reset.columns = ['vix_date', 'vix_close']
vix_reset['vix_date'] = pd.to_datetime(vix_reset['vix_date']).astype('datetime64[ns]')
vix_reset = vix_reset.dropna().sort_values('vix_date')
merged_vix = pd.merge_asof(df_for_merge, vix_reset, left_on='tw_date', right_on='vix_date', direction='backward')
df['vix_prev'] = merged_vix.set_index('tw_date')['vix_close']

df_clean = df.dropna(subset=['gap_ret', 'vix_prev', 'spy_1d_correct', 'spy_1d_buggy'])
N = len(df_clean)

print(f"\n  Dataset: {N} days, {df_clean.index[0].strftime('%Y-%m-%d')} to {df_clean.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# TEST 1: Binary signal ONLY (no VT, no VIX filter)
# ============================================================
print("\n\n[1] Binary signal ONLY — no VT sizing, no VIX filter")
print("=" * 70)

# Correct: SPY(T-1) > 0 → buy gap
sig_correct = (df_clean['spy_1d_correct'] > 0).astype(float)
ret_correct = df_clean['gap_ret'] * sig_correct

# Buggy: SPY(T) > 0 → buy gap (look-ahead)
sig_buggy = (df_clean['spy_1d_buggy'] > 0).astype(float)
ret_buggy = df_clean['gap_ret'] * sig_buggy

# Always-on
ret_always = df_clean['gap_ret']

for name, ret in [('Correct (T-1)', ret_correct), ('Buggy (T)', ret_buggy), ('Always-on', ret_always)]:
    ret = ret.dropna()
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    active = (ret != 0)
    trading_days = ret[active]
    if len(trading_days) > 10:
        t_stat, p_val = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat, p_val = 0, 1
    win_rate = (trading_days > 0).mean() * 100 if len(trading_days) > 0 else 0
    print(f"  {name:<20}: Sharpe={sharpe:.3f}, AnnRet={ann_ret*100:.2f}%, "
          f"Vol={ann_vol*100:.2f}%, t={t_stat:.3f}, WinRate={win_rate:.1f}%, "
          f"Active={active.sum()}/{N} ({active.mean()*100:.1f}%)")

# ============================================================
# TEST 2: With VIX filter, no VT
# ============================================================
print("\n\n[2] With VIX<25 filter, no VT sizing")
print("=" * 70)

vix_mask = (df_clean['vix_prev'] < 25).astype(float)

for name, spy_col in [('Correct (T-1)', 'spy_1d_correct'), ('Buggy (T)', 'spy_1d_buggy')]:
    sig = ((df_clean[spy_col] > 0) & (df_clean['vix_prev'] < 25)).astype(float)
    ret = df_clean['gap_ret'] * sig
    ret = ret.dropna()
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    active = (ret != 0)
    trading_days = ret[active]
    if len(trading_days) > 10:
        t_stat, _ = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat = 0
    win_rate = (trading_days > 0).mean() * 100 if len(trading_days) > 0 else 0
    print(f"  {name:<20}: Sharpe={sharpe:.3f}, AnnRet={ann_ret*100:.2f}%, "
          f"Vol={ann_vol*100:.2f}%, t={t_stat:.3f}, WinRate={win_rate:.1f}%, "
          f"Active={active.sum()}/{N}")

# ============================================================
# TEST 3: Full strategy (VT + VIX)
# ============================================================
print("\n\n[3] Full strategy (VT sizing + VIX<25)")
print("=" * 70)

vt_size = (8.63 / df_clean['vix_prev']).clip(upper=2.0)

for name, spy_col in [('Correct (T-1)', 'spy_1d_correct'), ('Buggy (T)', 'spy_1d_buggy')]:
    sig = ((df_clean[spy_col] > 0) & (df_clean['vix_prev'] < 25)).astype(float)
    weighted_sig = vt_size * sig
    gross = df_clean['gap_ret'] * weighted_sig
    net = gross - (5/10000) * weighted_sig  # 5 bps TX

    net = net.dropna()
    ann_ret = net.mean() * 252
    ann_vol = net.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + net).cumprod()
    peak = cum.cummax()
    mdd = ((cum - peak) / peak).min()
    active = (net != 0)
    trading_days = net[active]
    if len(trading_days) > 10:
        t_stat, _ = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat = 0
    win_rate = (trading_days > 0).mean() * 100 if len(trading_days) > 0 else 0

    print(f"  {name:<20}: Sharpe={sharpe:.3f}, AnnRet={ann_ret*100:.2f}%, "
          f"Vol={ann_vol*100:.2f}%, t={t_stat:.3f}, MDD={mdd*100:.2f}%, "
          f"WinRate={win_rate:.1f}%")

    # Average VT multiplier
    avg_vt = weighted_sig[weighted_sig > 0].mean()
    print(f"    Avg VT multiplier: {avg_vt:.3f}x")

# ============================================================
# TEST 4: Conditional gap return analysis
# ============================================================
print("\n\n[4] Conditional gap return analysis")
print("=" * 70)

spy_up_correct = df_clean['spy_1d_correct'] > 0
spy_up_buggy = df_clean['spy_1d_buggy'] > 0

print(f"  Mean gap return (all):            {df_clean['gap_ret'].mean()*100:.4f}% "
      f"(n={len(df_clean)})")
print(f"  Mean gap return (SPY T-1 > 0):    {df_clean.loc[spy_up_correct, 'gap_ret'].mean()*100:.4f}% "
      f"(n={spy_up_correct.sum()})")
print(f"  Mean gap return (SPY T-1 <= 0):   {df_clean.loc[~spy_up_correct, 'gap_ret'].mean()*100:.4f}% "
      f"(n={(~spy_up_correct).sum()})")
print(f"  Mean gap return (SPY T > 0):      {df_clean.loc[spy_up_buggy, 'gap_ret'].mean()*100:.4f}% "
      f"(n={spy_up_buggy.sum()})")
print(f"  Mean gap return (SPY T <= 0):     {df_clean.loc[~spy_up_buggy, 'gap_ret'].mean()*100:.4f}% "
      f"(n={(~spy_up_buggy).sum()})")

# T-test for conditional means
gap_up = df_clean.loc[spy_up_correct, 'gap_ret']
gap_down = df_clean.loc[~spy_up_correct, 'gap_ret']
t_diff, p_diff = stats.ttest_ind(gap_up, gap_down)
print(f"\n  T-test (gap|SPY_T-1>0 vs gap|SPY_T-1<=0):")
print(f"    Diff = {(gap_up.mean() - gap_down.mean())*100:.4f}%, t={t_diff:.3f}, p={p_diff:.6f}")

# Correlation
corr_correct = df_clean['spy_1d_correct'].corr(df_clean['gap_ret'])
corr_buggy = df_clean['spy_1d_buggy'].corr(df_clean['gap_ret'])
print(f"\n  Correlation(SPY_T-1_ret, TW_gap): {corr_correct:.4f}")
print(f"  Correlation(SPY_T_ret, TW_gap):   {corr_buggy:.4f}")

# ============================================================
# TEST 5: Year-by-year breakdown (binary, no VT)
# ============================================================
print("\n\n[5] Year-by-year: binary signal (correct T-1), no VT, no VIX")
print("=" * 70)

years = sorted(df_clean.index.year.unique())
print(f"  {'Year':>6} {'N':>5} {'Active':>6} {'MeanGap%':>9} {'MeanGap|Up%':>12} {'Sharpe':>7} {'WinRate%':>9}")

yearly_sharpes = []
for yr in years:
    mask = df_clean.index.year == yr
    d = df_clean[mask]
    sig = (d['spy_1d_correct'] > 0).astype(float)
    ret = d['gap_ret'] * sig
    active = (ret != 0).sum()
    if active < 10:
        continue
    trading = ret[ret != 0]
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sh = ann_ret / ann_vol if ann_vol > 0 else 0
    yearly_sharpes.append(sh)
    wr = (trading > 0).mean() * 100
    mean_gap_up = d.loc[d['spy_1d_correct'] > 0, 'gap_ret'].mean() * 100
    print(f"  {yr:>6} {len(d):>5} {active:>6} {d['gap_ret'].mean()*100:>9.4f} {mean_gap_up:>12.4f} {sh:>7.3f} {wr:>9.1f}")

print(f"\n  Mean yearly Sharpe: {np.mean(yearly_sharpes):.3f}")
print(f"  Std yearly Sharpe:  {np.std(yearly_sharpes):.3f}")
print(f"  Min yearly Sharpe:  {np.min(yearly_sharpes):.3f}")
print(f"  All positive: {'YES' if all(s > 0 for s in yearly_sharpes) else 'NO'}")

# ============================================================
# TEST 6: Verify the lag is actually correct
# ============================================================
print("\n\n[6] DETAILED date verification: first 10 days")
print("=" * 70)

# Get SPY dates and returns directly
spy_dates = spy_ret.index
print(f"  {'TW Date':<12} {'Gap%':>8} | {'Correct SPY (T-1)':>18} {'Buggy SPY (T)':>14}")
print(f"  {'':12} {'':>8} | {'date':>10} {'ret%':>7} {'date':>7} {'ret%':>7}")

for i, (idx, row) in enumerate(df_clean.head(10).iterrows()):
    tw_date = idx
    # Find which SPY dates were used
    # Correct: most recent SPY date < tw_date (shifted by 1 day)
    spy_before = spy_dates[spy_dates < tw_date]
    if len(spy_before) > 0:
        correct_spy_date = spy_before[-1]
        correct_spy_ret = spy_ret.loc[correct_spy_date]
    else:
        correct_spy_date = None
        correct_spy_ret = None

    # Buggy: most recent SPY date <= tw_date
    spy_on_or_before = spy_dates[spy_dates <= tw_date]
    if len(spy_on_or_before) > 0:
        buggy_spy_date = spy_on_or_before[-1]
        buggy_spy_ret = spy_ret.loc[buggy_spy_date]
    else:
        buggy_spy_date = None
        buggy_spy_ret = None

    print(f"  {tw_date.strftime('%Y-%m-%d'):<12} {row['gap_ret']*100:>7.3f}% | "
          f"{correct_spy_date.strftime('%Y-%m-%d') if correct_spy_date else 'N/A':>10} "
          f"{correct_spy_ret*100 if correct_spy_ret else 0:>6.3f}% "
          f"{buggy_spy_date.strftime('%Y-%m-%d') if buggy_spy_date else 'N/A':>10} "
          f"{buggy_spy_ret*100 if buggy_spy_ret else 0:>6.3f}%")

# ============================================================
# TEST 7: The critical insight — IS THIS JUST THE KNOWN I8 BUG?
# ============================================================
print("\n\n[7] Connection to I8 TZ Timing Bias")
print("=" * 70)
print("""
  I8 showed that SPY(T-1) strongly predicts Taiwan overnight gap.
  That's exactly what we're seeing here!

  The "correct" signal uses SPY(T-1) return (close T-1 / close T-2):
  - SPY closed at 4PM ET on T-1 = 5AM TST on T
  - Taiwan opens at 9AM TST on T
  - 4 hours between SPY close and TW open
  - Gap_ret = (TW_open_T - TW_close_T-1) / TW_close_T-1

  This is THE TZ information transmission channel we already documented!
  The gap captures SPY's overnight movement → Taiwan's opening reaction.

  BUT I8 showed this is NOT implementable at Sharpe 4+:
  - The gap is priced in by 9AM open → you can't trade it
  - You'd need to buy at TW close (T-1) based on SPY(T-1) signal
  - But SPY(T-1) closes AFTER TW(T-1) closes!
  - So you'd have to buy at TW close BEFORE seeing the signal!

  IMPLEMENTATION TIMELINE:
  1. TW closes at 1:30 PM TST (T-1)     ← decision point to buy overnight
  2. SPY opens at 10:30 PM TST (T-1)      ← signal not yet available
  3. SPY closes at 5:00 AM TST (T)         ← signal now available
  4. Taiwan opens at 9:00 AM TST (T)       ← gap already happened

  The strategy assumes we can:
  - Observe SPY(T-1) close at 5AM TST
  - Buy TW overnight exposure
  - Sell at TW open at 9AM TST

  With INDEX FUTURES this IS possible:
  - Taiwan index futures trade until 5AM next day (after-hours)
  - Or: buy SPY overnight → sell at TW open equivalent

  With SPOT (0050.TW) this is NOT possible:
  - Can't buy after TW market close
""")

# Check: can futures actually implement this?
# After-hours futures trading in Taiwan: 15:00 - 05:00 next day
print(f"  Taiwan futures after-hours: 3:00 PM to 5:00 AM next day")
print(f"  SPY close time: 5:00 AM TST")
print(f"  → Barely possible with after-hours futures!")
print(f"  → Buy futures at 5:01 AM (after SPY close), sell at 9:00 AM (TW open)")
print(f"  → Only 4 hours of exposure!")
print(f"  → But this IS a real implementable window!")

# ============================================================
# TEST 8: What about the INTRADAY component?
# ============================================================
print("\n\n[8] Gap-only vs Close-to-Close with correct signal")
print("=" * 70)

intraday_ret = (tw_close - tw_open) / tw_open
intraday_ret = intraday_ret.dropna()
outlier = intraday_ret.abs() > 0.15
if outlier.sum() > 0:
    intraday_ret.drop(intraday_ret[outlier].index, inplace=True)

df_clean['intraday_ret'] = intraday_ret
c2c_ret = tw_close.pct_change().dropna()
outlier = c2c_ret.abs() > 0.15
if outlier.sum() > 0:
    c2c_ret.drop(c2c_ret[outlier].index, inplace=True)
df_clean['c2c_ret'] = c2c_ret

# Signal: SPY(T-1) > 0
sig = (df_clean['spy_1d_correct'] > 0).astype(float)

for ret_name, ret_col in [('Gap (overnight)', 'gap_ret'),
                           ('Intraday', 'intraday_ret'),
                           ('Close-to-close', 'c2c_ret')]:
    valid = df_clean.dropna(subset=[ret_col])
    ret = valid[ret_col] * sig.reindex(valid.index).fillna(0)
    ret = ret.dropna()
    active = (ret != 0).sum()
    if active < 10:
        print(f"  {ret_name:<20}: insufficient data")
        continue
    trading = ret[ret != 0]
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sh = ann_ret / ann_vol if ann_vol > 0 else 0
    t_stat, _ = stats.ttest_1samp(trading, 0)
    print(f"  {ret_name:<20}: Sharpe={sh:.3f}, AnnRet={ann_ret*100:.2f}%, "
          f"Vol={ann_vol*100:.2f}%, t={t_stat:.3f}")

elapsed = time.time() - start_time
print(f"\n  Elapsed: {elapsed:.1f}s")
print("=" * 70)
