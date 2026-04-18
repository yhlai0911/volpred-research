#!/usr/bin/env python3
"""
K519: Premium Futures Strategy — Overnight Gap + VT Combined (大戶專屬)
=====================================================================
[提出: 用戶, 執行: Claude]

Background:
  K516: SPY>0 & VIX<25 overnight gap → Sharpe 0.93 at 5bp TX (5/5 cross-OOS)
  8.63/VIX monthly VT → Sharpe 0.84 for Taiwan (general investor best)
  Question: Can we combine overnight timing with VT risk-scaling?

Strategy designs (Taiwan index futures, TX=5bp):

  S1: Overnight Only (K516 baseline)
      SPY>0 & VIX<25 → buy at close, sell at open. Otherwise flat.

  S2: VT-Sized Overnight
      Position size = 8.63/VIX * leverage_factor
      Only enter when SPY>0 & VIX<25
      Combines VT risk-scaling + overnight timing

  S3: Full Day with Overnight Bias
      Always hold (like buy & hold)
      BUT: VIX>=25 → only hold overnight (avoid intraday crashes)
      VIX<25 → hold full day

  S4: Overnight Gap + Intraday VT
      Overnight: SPY-conditioned binary position
      Intraday: separate 8.63/VIX sized position
      Two segments managed independently

Benchmarks:
  B1: Buy & Hold 0050.TW
  B2: 8.63/VIX monthly VT (current best retail strategy)
  B3: K516 overnight only at 5bp (premium baseline)

Backtest: 2010-2025
TX cost: 5bp (大戶 futures)
Cross-OOS: 5 periods

Listing threshold:
  - Net Sharpe > 0.93 (K516 baseline)
  - Cross-OOS >= 4/5 positive
  - Label as 大戶/期貨專屬

References:
  - K516: Overnight Gap Futures — 5bp TX: Sharpe 0.93, 5/5 cross-OOS
  - K517: Monthly overnight gap — daily alpha diluted at monthly
  - 8.63/VIX monthly VT: Sharpe 0.84 (current Taiwan best)
  - Lou, Polk, Skouras (2019): A Tug of War: Overnight vs Intraday Returns, JFE
  - Moreira & Muir (2017): Volatility-Managed Portfolios, JoF
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

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K519: Premium Futures — Overnight Gap + VT Combined")
print("=" * 70)

print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

for df_raw in [tw50, spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

print(f"  0050.TW: {len(tw50)} days ({tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')})")
print(f"  SPY:     {len(spy)} days")
print(f"  VIX:     {len(vix)} days")

# ============================================================
# 2. Compute Returns
# ============================================================
print("\n[2] Computing returns...")

tw_close = tw50['Close'].copy()
tw_open = tw50['Open'].copy()
tw_high = tw50['High'].copy()
tw_low = tw50['Low'].copy()

valid_mask = (tw_close > 0) & (tw_open > 0) & tw_close.notna() & tw_open.notna()
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]
tw_high = tw_high[valid_mask]
tw_low = tw_low[valid_mask]

# Gap return = (Open_t - Close_{t-1}) / Close_{t-1}
gap_ret = (tw_open - tw_close.shift(1)) / tw_close.shift(1)
gap_ret = gap_ret.dropna()

# Intraday return = (Close_t - Open_t) / Open_t
intraday_ret = (tw_close - tw_open) / tw_open
intraday_ret = intraday_ret.dropna()

# Close-to-close return
c2c_ret = tw_close.pct_change().dropna()

# Remove outliers
for s in [gap_ret, intraday_ret, c2c_ret]:
    outlier = s.abs() > 0.15
    if outlier.sum() > 0:
        s.drop(s[outlier].index, inplace=True)

# SPY and VIX
spy_ret = spy['Close'].pct_change().dropna()
vix_close = vix['Close'].copy()

print(f"  Gap returns: {len(gap_ret)} obs, mean={gap_ret.mean()*10000:.2f} bps")
print(f"  Intraday returns: {len(intraday_ret)} obs, mean={intraday_ret.mean()*10000:.2f} bps")
print(f"  C2C returns: {len(c2c_ret)} obs, mean={c2c_ret.mean()*10000:.2f} bps")

# ============================================================
# 3. Align Data
# ============================================================
print("\n[3] Aligning data across markets...")

df = pd.DataFrame(index=tw50.index)
df['gap_ret'] = gap_ret
df['intraday_ret'] = intraday_ret
df['c2c_ret'] = c2c_ret
df['tw_close'] = tw_close
df['tw_open'] = tw_open

# SPY: merge_asof for previous US trading day
spy_daily = spy_ret.to_frame('spy_ret')
spy_reset = spy_daily.reset_index()
spy_reset.columns = ['spy_date', 'spy_ret']
spy_reset['spy_date'] = pd.to_datetime(spy_reset['spy_date'])
spy_reset = spy_reset.dropna().sort_values('spy_date')

df_reset = df.reset_index()
date_col = [c for c in df_reset.columns if 'date' in c.lower() or 'Date' in c or c == 'Price']
if date_col:
    date_col = date_col[0]
else:
    date_col = df_reset.columns[0]
if date_col != 'tw_date':
    df_reset.rename(columns={date_col: 'tw_date'}, inplace=True)
df_reset['tw_date'] = pd.to_datetime(df_reset['tw_date'])
df_for_merge = df_reset[['tw_date']].sort_values('tw_date')

merged = pd.merge_asof(df_for_merge, spy_reset, left_on='tw_date', right_on='spy_date', direction='backward')
df['spy_ret_prev'] = merged.set_index('tw_date')['spy_ret']

# VIX
vix_reset = vix_close.reset_index()
if isinstance(vix_reset.columns, pd.MultiIndex):
    vix_reset.columns = ['_'.join(str(c) for c in col).strip('_') for col in vix_reset.columns]
vix_reset.columns = ['vix_date', 'vix_close']
vix_reset['vix_date'] = pd.to_datetime(vix_reset['vix_date'])
vix_reset = vix_reset.dropna().sort_values('vix_date')

merged_vix = pd.merge_asof(df_for_merge, vix_reset, left_on='tw_date', right_on='vix_date', direction='backward')
df['vix_prev'] = merged_vix.set_index('tw_date')['vix_close']

df = df.dropna(subset=['gap_ret', 'intraday_ret', 'spy_ret_prev', 'vix_prev'])
print(f"  Aligned dataset: {len(df)} trading days")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 4. Descriptive Statistics
# ============================================================
print("\n[4] Descriptive Statistics")
print("=" * 70)

for name, series in [('Gap', df['gap_ret']), ('Intraday', df['intraday_ret']),
                      ('C2C', df['c2c_ret']), ('VIX', df['vix_prev'])]:
    print(f"  {name}: mean={series.mean():.6f}, std={series.std():.6f}, "
          f"skew={series.skew():.3f}, kurt={series.kurtosis():.3f}")

# VIX distribution for VT sizing
vix_s = df['vix_prev']
print(f"\n  VIX: min={vix_s.min():.1f}, p25={vix_s.quantile(0.25):.1f}, "
      f"med={vix_s.median():.1f}, p75={vix_s.quantile(0.75):.1f}, max={vix_s.max():.1f}")
print(f"  VIX<25 fraction: {(vix_s < 25).mean()*100:.1f}%")
print(f"  VIX<20 fraction: {(vix_s < 20).mean()*100:.1f}%")

# Gap-Intraday correlation
corr_gi = df['gap_ret'].corr(df['intraday_ret'])
print(f"\n  Gap-Intraday correlation: {corr_gi:.4f}")

# ============================================================
# 5. TX Cost Definition
# ============================================================
TX_COST = 0.0005  # 5bp round-trip (大戶 futures)
print(f"\n  TX cost: {TX_COST*10000:.0f} bps (大戶 futures)")

# ============================================================
# 6. Strategy Implementation (vectorized)
# ============================================================
print("\n[5] Strategy Backtests (Full Sample)")
print("=" * 70)


def compute_metrics(returns, name, n_total_days=None):
    """Compute strategy metrics from daily return series."""
    returns = returns.dropna()
    n = len(returns)
    if n < 30:
        return {'name': name, 'error': 'insufficient data'}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    mdd = ((cum - peak) / peak).min()
    total_ret = cum.iloc[-1] - 1

    # CAGR
    years = n / 252
    cagr = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 and cum.iloc[-1] > 0 else -1

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    # T-stat (Newey-West would be ideal, but simple t-test for speed)
    trading_days = returns[returns != 0]
    if len(trading_days) > 10:
        t_stat, p_val = stats.ttest_1samp(trading_days, 0)
    else:
        t_stat, p_val = 0.0, 1.0

    # Win rate
    win_rate = (trading_days > 0).mean() if len(trading_days) > 0 else 0

    # Exposure
    n_active = (returns != 0).sum()
    exposure = n_active / n_total_days if n_total_days else n_active / n

    # Avg daily return on active days (bps)
    avg_active_bps = trading_days.mean() * 10000 if len(trading_days) > 0 else 0

    return {
        'name': name,
        'n_days': n,
        'n_active_days': int(n_active),
        'exposure_pct': round(float(exposure * 100), 1),
        'avg_active_bps': round(float(avg_active_bps), 2),
        'win_rate_pct': round(float(win_rate * 100), 1),
        'ann_return_pct': round(float(ann_ret * 100), 2),
        'ann_vol_pct': round(float(ann_vol * 100), 2),
        'sharpe': round(float(sharpe), 3),
        'cagr_pct': round(float(cagr * 100), 2),
        'total_return_pct': round(float(total_ret * 100), 2),
        'mdd_pct': round(float(mdd * 100), 2),
        'calmar': round(float(calmar), 3),
        'sortino': round(float(sortino), 3),
        't_stat': round(float(t_stat), 3),
        'p_val': round(float(p_val), 4),
    }


def apply_tx(gross_ret, position_change, tx_cost):
    """Apply TX cost based on position changes.
    position_change: absolute change in position (for sizing strategies,
    this is |pos_t - pos_{t-1}|; for binary, it's 0 or 1).
    """
    return gross_ret - tx_cost * position_change


# --- Strategy 1: Overnight Only (K516 baseline) ---
# Binary: SPY>0 & VIX<25 → buy at close, sell at open next day.
# CRITICAL: Every signal day = 1 round-trip trade. TX charged per active day.
# (K516 model: strat_ret_net = gross - TX_COST * signal)
sig_s1 = ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < 25)).astype(float)
gross_s1 = df['gap_ret'] * sig_s1
net_s1 = gross_s1 - TX_COST * sig_s1  # TX every active day

# --- Strategy 2: VT-Sized Overnight ---
# Position size = 8.63/VIX, only when SPY>0 & VIX<25
# Every signal day is a round trip. TX proportional to position size.
vt_size = (8.63 / df['vix_prev']).clip(upper=2.0)
sig_s2_binary = ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < 25)).astype(float)
sig_s2 = vt_size * sig_s2_binary
gross_s2 = df['gap_ret'] * sig_s2
net_s2 = gross_s2 - TX_COST * sig_s2  # TX proportional to position size per day

# --- Strategy 3: Full Day with Overnight Bias ---
# VIX<25: hold full day (c2c return), buy & hold → TX only on regime switches
# VIX>=25: hold overnight only (gap return, sell at open → intraday out)
# TX model:
#   - During VIX<25 full-day holding: TX only when entering/exiting position
#   - During VIX>=25 overnight-only: 1 round trip per day (buy close, sell open)
#   - Regime switches: 1 additional trade
is_low_vix = (df['vix_prev'] < 25).astype(float)
is_high_vix = 1 - is_low_vix
gross_s3 = df['c2c_ret'] * is_low_vix + df['gap_ret'] * is_high_vix
# TX: high VIX days = 1 RT per day; regime transitions = 1 trade
regime_change_s3 = is_low_vix.diff().abs().fillna(0)
tx_s3 = TX_COST * is_high_vix + TX_COST * regime_change_s3  # daily RT during high VIX + transition cost
net_s3 = gross_s3 - tx_s3

# --- Strategy 4: Overnight Gap + Intraday VT ---
# Two independent legs:
# Leg A (overnight): SPY>0 & VIX<25 → 1x overnight position → 1 RT/day when active
# Leg B (intraday):  8.63/VIX sized position (always) → 1 RT/day (buy open, sell close)
sig_s4_overnight = ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < 25)).astype(float)
vt_intraday_size = (8.63 / df['vix_prev']).clip(upper=2.0)

gross_s4_leg_a = df['gap_ret'] * sig_s4_overnight
gross_s4_leg_b = df['intraday_ret'] * vt_intraday_size

# TX: each leg pays its own RT per active day
net_s4_a = gross_s4_leg_a - TX_COST * sig_s4_overnight  # Leg A: 1 RT per signal day
net_s4_b = gross_s4_leg_b - TX_COST * vt_intraday_size  # Leg B: 1 RT per day (always active)
net_s4 = net_s4_a + net_s4_b

# --- Benchmark 1: Buy & Hold 0050.TW ---
gross_bh = df['c2c_ret'].copy()
net_bh = gross_bh.copy()  # no TX for buy & hold

# --- Benchmark 2: 8.63/VIX Monthly VT ---
# Monthly rebalance: at month start, set weight = 8.63/VIX, cap at 2x
# Use beginning-of-month VIX
df['month'] = df.index.to_period('M')
month_first = df.groupby('month').first()
monthly_vt_weight = (8.63 / month_first['vix_prev']).clip(upper=2.0)
df['vt_weight'] = df['month'].map(monthly_vt_weight)
gross_vt = df['c2c_ret'] * df['vt_weight']
# TX: only on rebalance (monthly position change)
vt_pos_change = df['vt_weight'].diff().abs().fillna(df['vt_weight'].iloc[0])
# Only charge TX on month boundaries
is_month_start = df['month'] != df['month'].shift(1)
vt_tx = vt_pos_change * is_month_start.astype(float) * TX_COST
net_vt = gross_vt - vt_tx

# ============================================================
# 7. Compute All Metrics
# ============================================================
n_total = len(df)

all_strategies = {
    'S1_overnight_only': (net_s1, 'S1: Overnight Only (K516 baseline)'),
    'S2_vt_sized_overnight': (net_s2, 'S2: VT-Sized Overnight'),
    'S3_fullday_overnight_bias': (net_s3, 'S3: Full Day + Overnight Bias'),
    'S4_overnight_plus_intraday_vt': (net_s4, 'S4: Overnight Gap + Intraday VT'),
    'B1_buy_and_hold': (net_bh, 'B1: Buy & Hold 0050.TW'),
    'B2_vt_monthly': (net_vt, 'B2: 8.63/VIX Monthly VT'),
}

results = {}
for key, (ret_series, label) in all_strategies.items():
    m = compute_metrics(ret_series, label, n_total_days=n_total)
    results[key] = m
    print(f"\n--- {label} ---")
    if 'error' in m:
        print(f"  ERROR: {m['error']}")
        continue
    print(f"  Exposure: {m['exposure_pct']}%, Active days: {m['n_active_days']}")
    print(f"  Avg active day: {m['avg_active_bps']:.2f} bps, Win rate: {m['win_rate_pct']:.1f}%")
    print(f"  Net Sharpe: {m['sharpe']:.3f}, Ann Return: {m['ann_return_pct']:.2f}%, Vol: {m['ann_vol_pct']:.2f}%")
    print(f"  CAGR: {m['cagr_pct']:.2f}%, Total Return: {m['total_return_pct']:.2f}%, MDD: {m['mdd_pct']:.2f}%")
    print(f"  Calmar: {m['calmar']:.3f}, Sortino: {m['sortino']:.3f}")
    print(f"  t-stat: {m['t_stat']:.3f}, p-val: {m['p_val']:.4f}")

# ============================================================
# 8. Pairwise DM-like Comparison (S2-S4 vs S1 baseline)
# ============================================================
print("\n\n[6] Strategy Comparison vs K516 Baseline (S1)")
print("=" * 70)

baseline_ret = net_s1
comparisons = {}
for key in ['S2_vt_sized_overnight', 'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
    ret_series = all_strategies[key][0]
    label = all_strategies[key][1]
    # Align
    common = baseline_ret.index.intersection(ret_series.index)
    diff = ret_series.loc[common] - baseline_ret.loc[common]
    diff = diff.dropna()

    if len(diff) > 30:
        t, p = stats.ttest_1samp(diff, 0)
        mean_diff = diff.mean() * 252 * 100  # annualized % difference
    else:
        t, p, mean_diff = 0, 1, 0

    comparisons[key] = {
        'vs_baseline': 'S1_overnight_only',
        'ann_return_diff_pct': round(float(mean_diff), 2),
        't_stat': round(float(t), 3),
        'p_val': round(float(p), 4),
        'significant': bool(abs(t) > 1.96),
    }
    sig_marker = "***" if abs(t) > 3.0 else ("**" if abs(t) > 1.96 else "")
    print(f"  {label} vs S1: diff={mean_diff:+.2f}%/yr, t={t:.3f} {sig_marker}")

# ============================================================
# 9. Cross-OOS Validation (5 periods)
# ============================================================
print("\n\n[7] Cross-OOS Validation (5 periods)")
print("=" * 70)

oos_periods = [
    ('2013-01-01', '2015-12-31'),
    ('2016-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2021-01-01', '2023-06-30'),
    ('2023-07-01', '2025-12-31'),
]


def compute_strategy_returns_for_period(data):
    """Given a dataframe slice, compute all strategy returns."""
    n = len(data)
    if n < 30:
        return None

    # S1: Overnight Only — 1 RT per signal day
    sig1 = ((data['spy_ret_prev'] > 0) & (data['vix_prev'] < 25)).astype(float)
    g1 = data['gap_ret'] * sig1
    n1 = g1 - TX_COST * sig1

    # S2: VT-Sized Overnight — TX proportional to position size per day
    vt = (8.63 / data['vix_prev']).clip(upper=2.0)
    sig2_binary = ((data['spy_ret_prev'] > 0) & (data['vix_prev'] < 25)).astype(float)
    sig2 = vt * sig2_binary
    g2 = data['gap_ret'] * sig2
    n2 = g2 - TX_COST * sig2

    # S3: Full Day + Overnight Bias
    low_vix = (data['vix_prev'] < 25).astype(float)
    high_vix = 1 - low_vix
    g3 = data['c2c_ret'] * low_vix + data['gap_ret'] * high_vix
    rc3 = low_vix.diff().abs().fillna(0)
    tx3 = TX_COST * high_vix + TX_COST * rc3
    n3 = g3 - tx3

    # S4: Overnight + Intraday VT — each leg pays 1 RT per active day
    sig4a = ((data['spy_ret_prev'] > 0) & (data['vix_prev'] < 25)).astype(float)
    vt_intra = (8.63 / data['vix_prev']).clip(upper=2.0)
    g4a = data['gap_ret'] * sig4a
    n4a = g4a - TX_COST * sig4a
    g4b = data['intraday_ret'] * vt_intra
    n4b = g4b - TX_COST * vt_intra
    n4 = n4a + n4b

    # B1: Buy & Hold
    nb1 = data['c2c_ret'].copy()

    # B2: 8.63/VIX Monthly VT
    data_copy = data.copy()
    data_copy['month'] = data_copy.index.to_period('M')
    mf = data_copy.groupby('month').first()
    mw = (8.63 / mf['vix_prev']).clip(upper=2.0)
    data_copy['vt_w'] = data_copy['month'].map(mw)
    gb2 = data_copy['c2c_ret'] * data_copy['vt_w']
    vpc = data_copy['vt_w'].diff().abs().fillna(data_copy['vt_w'].iloc[0])
    ims = data_copy['month'] != data_copy['month'].shift(1)
    vtx = vpc * ims.astype(float) * TX_COST
    nb2 = gb2 - vtx

    return {
        'S1_overnight_only': n1,
        'S2_vt_sized_overnight': n2,
        'S3_fullday_overnight_bias': n3,
        'S4_overnight_plus_intraday_vt': n4,
        'B1_buy_and_hold': nb1,
        'B2_vt_monthly': nb2,
    }


oos_results = {k: [] for k in ['S1_overnight_only', 'S2_vt_sized_overnight',
                                 'S3_fullday_overnight_bias',
                                 'S4_overnight_plus_intraday_vt',
                                 'B1_buy_and_hold', 'B2_vt_monthly']}

for start, end in oos_periods:
    mask = (df.index >= start) & (df.index <= end)
    data_oos = df[mask]
    if len(data_oos) < 30:
        continue

    strat_rets = compute_strategy_returns_for_period(data_oos)
    if strat_rets is None:
        continue

    print(f"\n  Period: {start} to {end} ({len(data_oos)} days)")
    print(f"  {'Strategy':<38} {'Sharpe':>8} {'Ann Ret%':>10} {'MDD%':>8} {'Win%':>7}")

    for key in oos_results.keys():
        m = compute_metrics(strat_rets[key], key, n_total_days=len(data_oos))
        if 'error' in m:
            oos_results[key].append({
                'period': f"{start} to {end}",
                'n_days': len(data_oos),
                'sharpe': 0, 'ann_return_pct': 0, 'mdd_pct': 0,
                'win_rate_pct': 0, 't_stat': 0,
            })
        else:
            oos_results[key].append({
                'period': f"{start} to {end}",
                'n_days': m['n_days'],
                'sharpe': m['sharpe'],
                'ann_return_pct': m['ann_return_pct'],
                'mdd_pct': m['mdd_pct'],
                'win_rate_pct': m['win_rate_pct'],
                't_stat': m['t_stat'],
            })
            label = all_strategies.get(key, (None, key))[1] if key in all_strategies else key
            print(f"  {label:<38} {m['sharpe']:>8.3f} {m['ann_return_pct']:>9.2f}% {m['mdd_pct']:>7.2f}% {m['win_rate_pct']:>6.1f}%")

# Cross-OOS summary
print("\n\n--- Cross-OOS Summary ---")
print(f"  {'Strategy':<38} {'Positive/5':>10} {'Avg Sharpe':>12} {'Min Sharpe':>11}")
oos_summary = {}
for key in oos_results.keys():
    sharpes = [r['sharpe'] for r in oos_results[key]]
    n_positive = sum(1 for s in sharpes if s > 0)
    avg_sharpe = np.mean(sharpes) if sharpes else 0
    min_sharpe = min(sharpes) if sharpes else 0
    oos_summary[key] = {
        'n_positive': n_positive,
        'of_total': len(sharpes),
        'avg_sharpe': round(float(avg_sharpe), 3),
        'min_sharpe': round(float(min_sharpe), 3),
        'max_sharpe': round(float(max(sharpes)), 3) if sharpes else 0,
    }
    label = all_strategies.get(key, (None, key))[1] if key in all_strategies else key
    print(f"  {label:<38} {n_positive}/{len(sharpes):>8} {avg_sharpe:>12.3f} {min_sharpe:>11.3f}")

# ============================================================
# 10. Additional Analysis: Yearly Breakdown for Best Strategy
# ============================================================
print("\n\n[8] Yearly Breakdown")
print("=" * 70)

df['year'] = df.index.year
yearly_stats = {}

for year in sorted(df['year'].unique()):
    mask = df['year'] == year
    data_yr = df[mask]
    if len(data_yr) < 20:
        continue

    strat_rets = compute_strategy_returns_for_period(data_yr)
    if strat_rets is None:
        continue

    yr_metrics = {}
    for key in ['S1_overnight_only', 'S2_vt_sized_overnight',
                'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
        m = compute_metrics(strat_rets[key], key, n_total_days=len(data_yr))
        yr_metrics[key] = m.get('sharpe', 0)

    yearly_stats[int(year)] = yr_metrics

print(f"  {'Year':<6} {'S1 Sharpe':>10} {'S2 Sharpe':>10} {'S3 Sharpe':>10} {'S4 Sharpe':>10}")
for year in sorted(yearly_stats.keys()):
    ym = yearly_stats[year]
    print(f"  {year:<6} {ym.get('S1_overnight_only', 0):>10.3f} "
          f"{ym.get('S2_vt_sized_overnight', 0):>10.3f} "
          f"{ym.get('S3_fullday_overnight_bias', 0):>10.3f} "
          f"{ym.get('S4_overnight_plus_intraday_vt', 0):>10.3f}")

# ============================================================
# 11. Correlation Analysis: Strategy Returns
# ============================================================
print("\n\n[9] Strategy Return Correlations")
print("=" * 70)

corr_df = pd.DataFrame({
    'S1': net_s1,
    'S2': net_s2,
    'S3': net_s3,
    'S4': net_s4,
    'B&H': net_bh,
    'VT': net_vt,
}).dropna()

corr_matrix = corr_df.corr()
print(corr_matrix.round(3).to_string())

# ============================================================
# 12. Risk Analysis: Drawdown & Worst Periods
# ============================================================
print("\n\n[10] Worst Drawdown Periods")
print("=" * 70)

for key in ['S1_overnight_only', 'S2_vt_sized_overnight',
            'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
    ret_series = all_strategies[key][0]
    label = all_strategies[key][1]
    cum = (1 + ret_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak

    # Worst month
    monthly_ret = ret_series.resample('ME').sum()
    worst_month = monthly_ret.idxmin()
    worst_month_ret = monthly_ret.min()

    print(f"  {label}: MDD={dd.min()*100:.2f}%, "
          f"Worst month: {worst_month.strftime('%Y-%m')} ({worst_month_ret*100:.2f}%)")

# ============================================================
# 13. Sensitivity: VIX Threshold
# ============================================================
print("\n\n[11] VIX Threshold Sensitivity for S2 (VT-Sized Overnight)")
print("=" * 70)

vix_thresholds = [20, 22, 25, 28, 30, 35]
vix_sensitivity = {}
for vt in vix_thresholds:
    vt_s = (8.63 / df['vix_prev']).clip(upper=2.0)
    sig = vt_s * ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < vt)).astype(float)
    g = df['gap_ret'] * sig
    n = g - TX_COST * sig  # 1 RT per active day
    m = compute_metrics(n, f'VIX<{vt}', n_total_days=len(df))
    vix_sensitivity[vt] = m
    if 'error' not in m:
        print(f"  VIX<{vt}: Sharpe={m['sharpe']:.3f}, Return={m['ann_return_pct']:.2f}%, "
              f"MDD={m['mdd_pct']:.2f}%, Exposure={m['exposure_pct']:.1f}%")

# ============================================================
# 14. Sensitivity: Leverage Cap
# ============================================================
print("\n\n[12] Leverage Cap Sensitivity for S2")
print("=" * 70)

lev_caps = [1.0, 1.5, 2.0, 2.5, 3.0]
lev_sensitivity = {}
for cap in lev_caps:
    vt_s = (8.63 / df['vix_prev']).clip(upper=cap)
    sig = vt_s * ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < 25)).astype(float)
    g = df['gap_ret'] * sig
    n = g - TX_COST * sig  # 1 RT per active day
    m = compute_metrics(n, f'Cap={cap}x', n_total_days=len(df))
    lev_sensitivity[cap] = m
    if 'error' not in m:
        print(f"  Cap={cap}x: Sharpe={m['sharpe']:.3f}, Return={m['ann_return_pct']:.2f}%, "
              f"MDD={m['mdd_pct']:.2f}%, Sortino={m['sortino']:.3f}")

# ============================================================
# 15. DM Test: Best Strategy vs S1
# ============================================================
print("\n\n[13] Diebold-Mariano Style Test")
print("=" * 70)

# Use squared returns as loss (QLIKE proxy for return prediction)
# Actually for strategy comparison, just use return difference
# Already computed in section 8

for key, comp in comparisons.items():
    label = all_strategies[key][1]
    print(f"  {label} vs S1: diff={comp['ann_return_diff_pct']:+.2f}%/yr, "
          f"t={comp['t_stat']:.3f}, p={comp['p_val']:.4f}, "
          f"sig={'YES' if comp['significant'] else 'NO'}")

# ============================================================
# 16. Listing Criteria Check
# ============================================================
print("\n\n[14] Listing Criteria Check")
print("=" * 70)

listing_results = {}
for key in ['S1_overnight_only', 'S2_vt_sized_overnight',
            'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
    m = results[key]
    label = all_strategies[key][1]
    oos = oos_summary[key]

    sharpe_pass = m.get('sharpe', 0) > 0.93
    oos_pass = oos['n_positive'] >= 4
    harvey_pass = abs(m.get('t_stat', 0)) > 3.0
    all_pass = sharpe_pass and oos_pass and harvey_pass

    listing_results[key] = {
        'net_sharpe_5bp': m.get('sharpe', 0),
        'sharpe_gt_093': sharpe_pass,
        'cross_oos_positive': f"{oos['n_positive']}/{oos['of_total']}",
        'cross_oos_pass': oos_pass,
        't_stat': m.get('t_stat', 0),
        'harvey_pass': harvey_pass,
        'all_pass': all_pass,
    }

    print(f"\n  {label}:")
    print(f"    Net Sharpe (5bp): {m.get('sharpe', 0):.3f} {'PASS' if sharpe_pass else 'FAIL'} (>0.93)")
    print(f"    Cross-OOS: {oos['n_positive']}/{oos['of_total']} {'PASS' if oos_pass else 'FAIL'} (>=4/5)")
    print(f"    Harvey t-stat: {m.get('t_stat', 0):.3f} {'PASS' if harvey_pass else 'FAIL'} (>3.0)")
    print(f"    ALL PASS: {'YES ★★' if all_pass else 'NO'}")

# ============================================================
# 17. Compile Results JSON
# ============================================================
elapsed = time.time() - start_time

output = {
    'experiment_id': 'K519',
    'title': 'Premium Futures Strategy — Overnight Gap + VT Combined (大戶專屬)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'attribution': '[提出: 用戶, 執行: Claude]',
    'data_source': 'yfinance: 0050.TW (gap/intraday return proxy), SPY, ^VIX',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': len(df),
    'tx_cost_bps': 5.0,
    'tx_note': '大戶 futures (TX/MTX) round-trip',
    'references': [
        'K516: Overnight Gap Futures — Sharpe 0.93 at 5bp TX, 5/5 cross-OOS',
        'K517: Monthly overnight gap — daily alpha diluted at monthly',
        '8.63/VIX monthly VT: Sharpe 0.84 (current Taiwan best retail)',
        'Lou, Polk, Skouras (2019): A Tug of War: Overnight vs Intraday Returns, JFE',
        'Moreira & Muir (2017): Volatility-Managed Portfolios, JoF',
    ],
    'descriptive_statistics': {
        'gap_ret_mean_bps': round(float(df['gap_ret'].mean() * 10000), 2),
        'gap_ret_std_bps': round(float(df['gap_ret'].std() * 10000), 2),
        'intraday_ret_mean_bps': round(float(df['intraday_ret'].mean() * 10000), 2),
        'intraday_ret_std_bps': round(float(df['intraday_ret'].std() * 10000), 2),
        'c2c_ret_mean_bps': round(float(df['c2c_ret'].mean() * 10000), 2),
        'gap_intraday_corr': round(float(corr_gi), 4),
        'vix_median': round(float(df['vix_prev'].median()), 1),
        'vix_lt25_pct': round(float((df['vix_prev'] < 25).mean() * 100), 1),
    },
    'strategy_designs': {
        'S1_overnight_only': 'SPY>0 & VIX<25 → 1x overnight position. K516 baseline.',
        'S2_vt_sized_overnight': 'SPY>0 & VIX<25 → (8.63/VIX) overnight position. VT risk-scaling + overnight timing.',
        'S3_fullday_overnight_bias': 'VIX<25: full day hold. VIX>=25: overnight only.',
        'S4_overnight_plus_intraday_vt': 'Leg A: SPY-conditioned overnight. Leg B: 8.63/VIX intraday. Independent.',
    },
    'full_sample_results': results,
    'comparisons_vs_baseline': comparisons,
    'cross_oos_results': oos_results,
    'cross_oos_summary': oos_summary,
    'yearly_sharpes': yearly_stats,
    'correlation_matrix': corr_matrix.round(4).to_dict(),
    'vix_threshold_sensitivity': {str(k): v for k, v in vix_sensitivity.items()},
    'leverage_cap_sensitivity': {str(k): v for k, v in lev_sensitivity.items()},
    'listing_criteria': listing_results,
    'practical_caveats': [
        '0050.TW gap != TX futures gap (basis risk, delivery month effects)',
        'Taiwan futures night session has thin liquidity for overnight entries',
        'TX margin ~NT$184,000/contract, MTX ~NT$46,000',
        'Monthly roll cost not included in TX estimates',
        'Slippage at open/close auctions may exceed our 5bp estimate',
        'VT sizing with leverage cap 2x — uncapped could be dangerous',
        '大戶/期貨專屬：一般投資人無法以 5bp 執行',
    ],
    'elapsed_seconds': round(elapsed, 1),
}

# Determine key findings
best_strat = max(
    ['S1_overnight_only', 'S2_vt_sized_overnight',
     'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt'],
    key=lambda k: results[k].get('sharpe', 0) if 'error' not in results[k] else -999
)
best_sharpe = results[best_strat].get('sharpe', 0)
best_label = all_strategies[best_strat][1]

findings = [
    f"Best combined strategy: {best_label} — Net Sharpe {best_sharpe:.3f}",
    f"K516 baseline (S1): Net Sharpe {results['S1_overnight_only'].get('sharpe', 0):.3f}",
    f"8.63/VIX monthly VT (B2): Net Sharpe {results['B2_vt_monthly'].get('sharpe', 0):.3f}",
    f"Buy & Hold (B1): Sharpe {results['B1_buy_and_hold'].get('sharpe', 0):.3f}",
]

# Check if any strategy beats K516
for key in ['S2_vt_sized_overnight', 'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
    s = results[key].get('sharpe', 0)
    label = all_strategies[key][1]
    if s > 0.93:
        findings.append(f"★ {label} beats K516 baseline! Sharpe {s:.3f} > 0.93")
    else:
        findings.append(f"{label}: Sharpe {s:.3f} < 0.93 (fails to beat K516)")

# Cross-OOS
for key in ['S1_overnight_only', 'S2_vt_sized_overnight',
            'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt']:
    oos = oos_summary[key]
    label = all_strategies[key][1]
    findings.append(f"{label} cross-OOS: {oos['n_positive']}/{oos['of_total']} positive")

# Listing conclusion
any_pass = any(v['all_pass'] for v in listing_results.values())
if any_pass:
    passing = [k for k, v in listing_results.items() if v['all_pass']]
    findings.append(f"LISTING CRITERIA MET: {', '.join(passing)}")
else:
    findings.append("No strategy meets all listing criteria (Sharpe>0.93, OOS>=4/5, Harvey t>3.0)")

output['key_findings'] = findings

# Conclusion
output['conclusion'] = (
    f"Best combined: {best_label} (Sharpe {best_sharpe:.3f}). "
    f"S1 baseline: {results['S1_overnight_only'].get('sharpe', 0):.3f}. "
    f"{'VT sizing improves' if best_sharpe > results['S1_overnight_only'].get('sharpe', 0) else 'Binary signal already optimal'}. "
    f"Listing: {'PASS' if any_pass else 'FAIL'}."
)

# Save
results_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a7e9aa82/experiments/k519_premium_futures_results.json'
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n\nResults saved to: {results_path}")
print(f"Elapsed: {elapsed:.1f}s")

# ============================================================
# Final Summary
# ============================================================
print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)

print(f"\n{'Strategy':<42} {'Sharpe':>8} {'Return%':>9} {'MDD%':>8} {'OOS':>6}")
print("-" * 73)
for key in ['S1_overnight_only', 'S2_vt_sized_overnight',
            'S3_fullday_overnight_bias', 'S4_overnight_plus_intraday_vt',
            'B1_buy_and_hold', 'B2_vt_monthly']:
    m = results[key]
    label = all_strategies[key][1]
    oos = oos_summary[key]
    if 'error' not in m:
        print(f"  {label:<40} {m['sharpe']:>8.3f} {m['ann_return_pct']:>8.2f}% "
              f"{m['mdd_pct']:>7.2f}% {oos['n_positive']}/{oos['of_total']:>3}")

print(f"\nConclusion: {output['conclusion']}")
print(f"\n{'★ 大戶/期貨專屬策略 — 一般投資人無法以此 TX 執行 ★'}")
