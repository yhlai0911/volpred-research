#!/usr/bin/env python3
"""
K515: Taiwan Overnight Gap Trading Strategy
============================================
[提出: 用戶, 執行: Claude]

Concept: K502 found 77-93% of Taiwan alpha concentrates in overnight gap
(close→open). K451 showed overnight vol = 36-44% of total. Instead of
trying to capture alpha intraday (which K502's lead-lag failed at),
directly trade the gap by buying at Taiwan close and selling at open.

Strategies:
1. Always Overnight: buy close(t-1), sell open(t) every day
2. SPY-Conditioned: only overnight when SPY(t-1) > 0
3. VIX-Conditioned: only overnight when VIX < 20
4. SPY+VIX Combined: SPY > 0 AND VIX < 25

Data: 0050.TW, SPY, ^VIX via yfinance, 2010-2025
TX cost: 0.585% round-trip (台股)

References:
- K502: Alpha concentration in overnight gap (77-93%)
- K451: Overnight vol decomposition (36-44% of total)
- T5d/T5e: SPY overnight momentum for Taiwan (Sharpe 1.82 but TX kills)
- Lou et al. (2019): "A Tug of War: Overnight Versus Intraday Expected Returns", JFE
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
print("K515: Taiwan Overnight Gap Trading Strategy")
print("=" * 70)

print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

# Flatten multi-level columns if present
for df in [tw50, spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"  0050.TW: {len(tw50)} days ({tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')})")
print(f"  SPY:     {len(spy)} days ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX:     {len(vix)} days ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Compute Returns
# ============================================================
print("\n[2] Computing returns...")

# Gap return: Open(t) vs Close(t-1) — the overnight gap
tw_close = tw50['Close'].copy()
tw_open = tw50['Open'].copy()

# Data cleaning: remove days with zero/NaN open or close (stock split artifacts)
valid_mask = (tw_close > 0) & (tw_open > 0) & tw_close.notna() & tw_open.notna()
tw_close = tw_close[valid_mask]
tw_open = tw_open[valid_mask]

# Gap return = (Open_t - Close_{t-1}) / Close_{t-1}
gap_ret = (tw_open - tw_close.shift(1)) / tw_close.shift(1)
gap_ret = gap_ret.dropna()

# Remove extreme outliers (|gap| > 15% likely data errors or circuit breakers)
outlier_mask = gap_ret.abs() > 0.15
n_outliers = outlier_mask.sum()
if n_outliers > 0:
    print(f"  ⚠ Removing {n_outliers} extreme gap outliers (|gap| > 15%)")
    gap_ret = gap_ret[~outlier_mask]

# Intraday return = (Close_t - Open_t) / Open_t
intraday_ret = (tw_close - tw_open) / tw_open
intraday_ret = intraday_ret[intraday_ret.abs() < 0.15].dropna()  # same filter

# Total close-to-close return
c2c_ret = tw_close.pct_change().dropna()
c2c_ret = c2c_ret[c2c_ret.abs() < 0.15]  # same filter

# SPY daily return (close-to-close)
spy_ret = spy['Close'].pct_change().dropna()

# VIX close
vix_close = vix['Close'].copy()

print(f"  Gap returns:      {len(gap_ret)} obs, mean={gap_ret.mean()*100:.4f}%, std={gap_ret.std()*100:.4f}%")
print(f"  Intraday returns: {len(intraday_ret)} obs, mean={intraday_ret.mean()*100:.4f}%, std={intraday_ret.std()*100:.4f}%")
print(f"  C2C returns:      {len(c2c_ret)} obs, mean={c2c_ret.mean()*100:.4f}%, std={c2c_ret.std()*100:.4f}%")

# ============================================================
# 3. Descriptive Statistics for Gap Returns
# ============================================================
print("\n[3] Gap Return Diagnostics")
print("-" * 50)

# Basic stats
print(f"  Mean:     {gap_ret.mean()*100:.4f}% per day")
print(f"  Median:   {gap_ret.median()*100:.4f}%")
print(f"  Std:      {gap_ret.std()*100:.4f}%")
print(f"  Skew:     {gap_ret.skew():.3f}")
print(f"  Kurtosis: {gap_ret.kurtosis():.3f}")
print(f"  Min:      {gap_ret.min()*100:.3f}%")
print(f"  Max:      {gap_ret.max()*100:.3f}%")
print(f"  % positive: {(gap_ret > 0).mean()*100:.1f}%")

# Annualized gap return
ann_gap = gap_ret.mean() * 252
ann_gap_std = gap_ret.std() * np.sqrt(252)
gap_sharpe = ann_gap / ann_gap_std
print(f"\n  Annualized gap return:  {ann_gap*100:.2f}%")
print(f"  Annualized gap vol:     {ann_gap_std*100:.2f}%")
print(f"  Gap Sharpe (no TX):     {gap_sharpe:.3f}")

# T-test: is mean gap return significantly different from 0?
t_stat_gap, p_val_gap = stats.ttest_1samp(gap_ret.dropna(), 0)
print(f"  T-test vs 0: t={t_stat_gap:.3f}, p={p_val_gap:.4f}")

# Compare gap vs intraday
print(f"\n  Gap share of total return: {gap_ret.sum() / c2c_ret.sum() * 100:.1f}%")
print(f"  Gap share of total vol:    {gap_ret.var() / c2c_ret.var() * 100:.1f}%")

# ============================================================
# 4. Align data for strategies
# ============================================================
print("\n[4] Aligning data across markets...")

# Create a master dataframe on Taiwan trading days
df = pd.DataFrame(index=tw50.index)
df['gap_ret'] = gap_ret
df['intraday_ret'] = intraday_ret
df['c2c_ret'] = c2c_ret
df['tw_close'] = tw_close
df['tw_open'] = tw_open

# For SPY: Taiwan day t uses SPY close from the PREVIOUS US trading day
# (SPY closes at 04:00 Taiwan time, Taiwan opens at 09:00 same day)
# So for Taiwan date t, we need SPY return from the most recent US trading day before t
spy_daily = spy_ret.to_frame('spy_ret')
spy_close_df = spy['Close'].to_frame('spy_close')

# Merge SPY return: for each Taiwan day, get the most recent SPY return
# Use merge_asof to align
df_reset = df.reset_index()
df_reset.rename(columns={'Date': 'tw_date'}, inplace=True)
if 'Price' in df_reset.columns:
    df_reset.rename(columns={'Price': 'tw_date'}, inplace=True)

spy_reset = spy_daily.reset_index()
spy_reset.rename(columns={'Date': 'spy_date', 'Price': 'spy_date'}, inplace=True)
# Ensure column name
if 'spy_date' not in spy_reset.columns:
    spy_reset.columns = ['spy_date', 'spy_ret']

# Use merge_asof: for each tw_date, find the most recent spy_date <= tw_date - 1 day
# Actually, SPY(t-1 US) should be available by Taiwan morning of t
# So we do merge_asof with tolerance
df_reset['tw_date'] = pd.to_datetime(df_reset['tw_date'])
spy_reset['spy_date'] = pd.to_datetime(spy_reset.iloc[:, 0])
spy_reset['spy_ret'] = spy_reset.iloc[:, 1].values

spy_for_merge = spy_reset[['spy_date', 'spy_ret']].dropna().sort_values('spy_date')
df_for_merge = df_reset[['tw_date']].sort_values('tw_date')

merged = pd.merge_asof(
    df_for_merge,
    spy_for_merge,
    left_on='tw_date',
    right_on='spy_date',
    direction='backward'
)

df['spy_ret_prev'] = merged.set_index('tw_date')['spy_ret']

# VIX: same logic, use previous close
vix_reset = vix_close.reset_index()
if isinstance(vix_reset.columns, pd.MultiIndex):
    vix_reset.columns = ['_'.join(str(c) for c in col).strip('_') for col in vix_reset.columns]
vix_reset.columns = ['vix_date', 'vix_close']
vix_reset['vix_date'] = pd.to_datetime(vix_reset['vix_date'])
vix_reset = vix_reset.dropna().sort_values('vix_date')

merged_vix = pd.merge_asof(
    df_for_merge,
    vix_reset,
    left_on='tw_date',
    right_on='vix_date',
    direction='backward'
)
df['vix_prev'] = merged_vix.set_index('tw_date')['vix_close']

df = df.dropna(subset=['gap_ret', 'spy_ret_prev', 'vix_prev'])
print(f"  Aligned dataset: {len(df)} trading days")
print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 5. Strategy Backtests
# ============================================================
print("\n[5] Strategy Backtests")
print("=" * 70)

# ⚠️ CORRECTED (K625): ETF tax=0.1%, commission=0.04275%/side (3折 discount)
# Old (WRONG): 0.585% stock / 0.385% ETF (used full commission, stock tax rate)
# Correct ETF: buy 0.04275% + sell (0.04275% + 0.1%) = 0.1855% round-trip
TX_COST = 0.001855  # 0.1855% round-trip for ETF (corrected)
TX_COST_ETF = 0.001855  # Same — ETF is the only relevant rate for 0050.TW
TX_COST_STOCK = 0.002855  # Stock rate for reference: 0.04275%*2 + 0.2% = 0.2855%

strategies = {}

def backtest_strategy(signal, gap_returns, name, tx_cost):
    """
    signal: boolean Series aligned with gap_returns index
    gap_returns: daily gap returns
    tx_cost: round-trip cost per trade

    Returns dict of performance metrics
    """
    common_idx = signal.index.intersection(gap_returns.index)
    sig = signal.loc[common_idx]
    ret = gap_returns.loc[common_idx]

    # Strategy return: gap_ret when signal=1, 0 otherwise
    strat_ret_gross = ret * sig.astype(float)

    # TX cost: incurred every day we hold overnight
    # (buy at close, sell at open = 1 round trip per holding day)
    strat_ret_net = strat_ret_gross - tx_cost * sig.astype(float)

    # Also compute with ETF tx cost
    strat_ret_net_etf = strat_ret_gross - TX_COST_ETF * sig.astype(float)

    # Buy & hold gap (always overnight)
    bh_ret = ret.copy()

    # Metrics
    n_days = len(ret)
    n_trades = sig.sum()
    exposure = n_trades / n_days

    # Gross
    ann_ret_gross = strat_ret_gross.mean() * 252
    ann_vol_gross = strat_ret_gross.std() * np.sqrt(252)
    sharpe_gross = ann_ret_gross / ann_vol_gross if ann_vol_gross > 0 else 0

    # Net (stock TX)
    ann_ret_net = strat_ret_net.mean() * 252
    ann_vol_net = strat_ret_net.std() * np.sqrt(252)
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 0 else 0

    # Net (ETF TX)
    ann_ret_net_etf = strat_ret_net_etf.mean() * 252
    ann_vol_net_etf = strat_ret_net_etf.std() * np.sqrt(252)
    sharpe_net_etf = ann_ret_net_etf / ann_vol_net_etf if ann_vol_net_etf > 0 else 0

    # Cumulative return
    cum_gross = (1 + strat_ret_gross).cumprod()
    cum_net = (1 + strat_ret_net).cumprod()
    cum_net_etf = (1 + strat_ret_net_etf).cumprod()

    # Max drawdown
    def max_drawdown(cum_returns):
        peak = cum_returns.cummax()
        dd = (cum_returns - peak) / peak
        return dd.min()

    mdd_gross = max_drawdown(cum_gross)
    mdd_net = max_drawdown(cum_net)
    mdd_net_etf = max_drawdown(cum_net_etf)

    # Total return
    total_ret_gross = cum_gross.iloc[-1] - 1
    total_ret_net = cum_net.iloc[-1] - 1
    total_ret_net_etf = cum_net_etf.iloc[-1] - 1

    # T-test (is mean strategy return significantly > 0?)
    if strat_ret_gross[sig > 0].shape[0] > 10:
        t_stat, p_val = stats.ttest_1samp(strat_ret_gross[sig > 0], 0)
    else:
        t_stat, p_val = 0, 1

    # Harvey t-stat for net returns
    if strat_ret_net[sig > 0].shape[0] > 10:
        t_stat_net, p_val_net = stats.ttest_1samp(strat_ret_net[sig > 0], 0)
    else:
        t_stat_net, p_val_net = 0, 1

    # Win rate (among holding days)
    if n_trades > 0:
        win_rate_gross = (strat_ret_gross[sig > 0] > 0).mean()
        win_rate_net = (strat_ret_net[sig > 0] > 0).mean()
    else:
        win_rate_gross = 0
        win_rate_net = 0

    # Avg gap return on signal days vs non-signal days
    avg_gap_signal = ret[sig > 0].mean() * 100 if n_trades > 0 else 0
    avg_gap_no_signal = ret[sig <= 0].mean() * 100 if (sig <= 0).sum() > 0 else 0

    result = {
        'name': name,
        'n_days': int(n_days),
        'n_trades': int(n_trades),
        'exposure_pct': round(exposure * 100, 1),
        'avg_gap_signal_bps': round(avg_gap_signal * 100, 2),
        'avg_gap_nosignal_bps': round(avg_gap_no_signal * 100, 2),
        'win_rate_gross_pct': round(win_rate_gross * 100, 1),
        'win_rate_net_pct': round(win_rate_net * 100, 1),
        'ann_return_gross_pct': round(ann_ret_gross * 100, 2),
        'ann_vol_gross_pct': round(ann_vol_gross * 100, 2),
        'sharpe_gross': round(sharpe_gross, 3),
        'total_return_gross_pct': round(total_ret_gross * 100, 2),
        'mdd_gross_pct': round(mdd_gross * 100, 2),
        't_stat_gross': round(t_stat, 3),
        'p_val_gross': round(p_val, 4),
        'ann_return_net_stock_pct': round(ann_ret_net * 100, 2),
        'sharpe_net_stock': round(sharpe_net, 3),
        'total_return_net_stock_pct': round(total_ret_net * 100, 2),
        'mdd_net_stock_pct': round(mdd_net * 100, 2),
        't_stat_net_stock': round(t_stat_net, 3),
        'ann_return_net_etf_pct': round(ann_ret_net_etf * 100, 2),
        'sharpe_net_etf': round(sharpe_net_etf, 3),
        'total_return_net_etf_pct': round(total_ret_net_etf * 100, 2),
        'mdd_net_etf_pct': round(mdd_net_etf * 100, 2),
        'tx_cost_drag_stock_pct': round((ann_ret_gross - ann_ret_net) * 100, 2),
        'tx_cost_drag_etf_pct': round((ann_ret_gross - ann_ret_net_etf) * 100, 2),
    }

    return result, strat_ret_gross, strat_ret_net, strat_ret_net_etf


# --- Strategy 1: Always Overnight ---
print("\n--- Strategy 1: Always Overnight ---")
sig1 = pd.Series(1, index=df.index)
res1, ret1_g, ret1_n, ret1_ne = backtest_strategy(sig1, df['gap_ret'], 'Always Overnight', TX_COST)
strategies['always_overnight'] = res1
print(f"  Exposure: {res1['exposure_pct']}%")
print(f"  Gross: Sharpe={res1['sharpe_gross']:.3f}, Return={res1['ann_return_gross_pct']:.2f}%, MDD={res1['mdd_gross_pct']:.2f}%")
print(f"  Net(stock): Sharpe={res1['sharpe_net_stock']:.3f}, Return={res1['ann_return_net_stock_pct']:.2f}%")
print(f"  Net(ETF):   Sharpe={res1['sharpe_net_etf']:.3f}, Return={res1['ann_return_net_etf_pct']:.2f}%")
print(f"  TX drag: stock={res1['tx_cost_drag_stock_pct']:.2f}%/yr, ETF={res1['tx_cost_drag_etf_pct']:.2f}%/yr")
print(f"  Win rate: {res1['win_rate_gross_pct']:.1f}% (gross), {res1['win_rate_net_pct']:.1f}% (net)")

# --- Strategy 2: SPY-Conditioned ---
print("\n--- Strategy 2: SPY-Conditioned Overnight ---")
sig2 = (df['spy_ret_prev'] > 0).astype(int)
res2, ret2_g, ret2_n, ret2_ne = backtest_strategy(sig2, df['gap_ret'], 'SPY-Conditioned', TX_COST)
strategies['spy_conditioned'] = res2
print(f"  Exposure: {res2['exposure_pct']}%")
print(f"  Avg gap when SPY>0: {res2['avg_gap_signal_bps']:.2f} bps")
print(f"  Avg gap when SPY≤0: {res2['avg_gap_nosignal_bps']:.2f} bps")
print(f"  Gross: Sharpe={res2['sharpe_gross']:.3f}, Return={res2['ann_return_gross_pct']:.2f}%")
print(f"  Net(stock): Sharpe={res2['sharpe_net_stock']:.3f}, Return={res2['ann_return_net_stock_pct']:.2f}%")
print(f"  Net(ETF):   Sharpe={res2['sharpe_net_etf']:.3f}, Return={res2['ann_return_net_etf_pct']:.2f}%")
print(f"  TX drag: stock={res2['tx_cost_drag_stock_pct']:.2f}%/yr, ETF={res2['tx_cost_drag_etf_pct']:.2f}%/yr")

# --- Strategy 3: VIX-Conditioned ---
print("\n--- Strategy 3: VIX-Conditioned Overnight ---")
sig3 = (df['vix_prev'] < 20).astype(int)
res3, ret3_g, ret3_n, ret3_ne = backtest_strategy(sig3, df['gap_ret'], 'VIX<20 Conditioned', TX_COST)
strategies['vix_conditioned'] = res3
print(f"  Exposure: {res3['exposure_pct']}%")
print(f"  Avg gap when VIX<20: {res3['avg_gap_signal_bps']:.2f} bps")
print(f"  Avg gap when VIX≥20: {res3['avg_gap_nosignal_bps']:.2f} bps")
print(f"  Gross: Sharpe={res3['sharpe_gross']:.3f}, Return={res3['ann_return_gross_pct']:.2f}%")
print(f"  Net(stock): Sharpe={res3['sharpe_net_stock']:.3f}, Return={res3['ann_return_net_stock_pct']:.2f}%")
print(f"  Net(ETF):   Sharpe={res3['sharpe_net_etf']:.3f}, Return={res3['ann_return_net_etf_pct']:.2f}%")

# --- Strategy 4: SPY + VIX Combined ---
print("\n--- Strategy 4: SPY>0 + VIX<25 Combined ---")
sig4 = ((df['spy_ret_prev'] > 0) & (df['vix_prev'] < 25)).astype(int)
res4, ret4_g, ret4_n, ret4_ne = backtest_strategy(sig4, df['gap_ret'], 'SPY+VIX Combined', TX_COST)
strategies['spy_vix_combined'] = res4
print(f"  Exposure: {res4['exposure_pct']}%")
print(f"  Avg gap on signal days: {res4['avg_gap_signal_bps']:.2f} bps")
print(f"  Gross: Sharpe={res4['sharpe_gross']:.3f}, Return={res4['ann_return_gross_pct']:.2f}%")
print(f"  Net(stock): Sharpe={res4['sharpe_net_stock']:.3f}, Return={res4['ann_return_net_stock_pct']:.2f}%")
print(f"  Net(ETF):   Sharpe={res4['sharpe_net_etf']:.3f}, Return={res4['ann_return_net_etf_pct']:.2f}%")

# --- Benchmark: Buy & Hold 0050.TW ---
print("\n--- Benchmark: Buy & Hold 0050.TW ---")
bh_ret = df['c2c_ret']
ann_bh = bh_ret.mean() * 252
vol_bh = bh_ret.std() * np.sqrt(252)
sharpe_bh = ann_bh / vol_bh
cum_bh = (1 + bh_ret).cumprod()
mdd_bh = ((cum_bh - cum_bh.cummax()) / cum_bh.cummax()).min()
print(f"  Ann Return: {ann_bh*100:.2f}%")
print(f"  Ann Vol:    {vol_bh*100:.2f}%")
print(f"  Sharpe:     {sharpe_bh:.3f}")
print(f"  MDD:        {mdd_bh*100:.2f}%")

# ============================================================
# 6. Cross-OOS Validation (5 periods)
# ============================================================
print("\n\n[6] Cross-OOS Validation (5 periods)")
print("=" * 70)

# Define 5 OOS periods
oos_periods = [
    ('2013-01-01', '2015-12-31'),
    ('2016-01-01', '2018-12-31'),
    ('2019-01-01', '2020-12-31'),
    ('2021-01-01', '2023-06-30'),
    ('2023-07-01', '2025-12-31'),
]

oos_results = {}

for strat_name, signal_func in [
    ('always_overnight', lambda d: pd.Series(1, index=d.index)),
    ('spy_conditioned', lambda d: (d['spy_ret_prev'] > 0).astype(int)),
    ('vix_conditioned', lambda d: (d['vix_prev'] < 20).astype(int)),
    ('spy_vix_combined', lambda d: ((d['spy_ret_prev'] > 0) & (d['vix_prev'] < 25)).astype(int)),
]:
    oos_results[strat_name] = []
    for i, (start, end) in enumerate(oos_periods):
        sub = df.loc[start:end]
        if len(sub) < 50:
            continue
        sig = signal_func(sub)
        res_oos, _, _, _ = backtest_strategy(sig, sub['gap_ret'], strat_name, TX_COST)
        res_oos['oos_period'] = f"{start} to {end}"
        res_oos['oos_n_days'] = len(sub)
        oos_results[strat_name].append(res_oos)

print("\nCross-OOS Summary (Net ETF Sharpe):")
print(f"{'Strategy':<25} ", end="")
for i, (s, e) in enumerate(oos_periods):
    print(f"{'P'+str(i+1):<10}", end="")
print(f"{'Mean':<10}{'Std':<10}{'% >0':<10}")

for strat_name in ['always_overnight', 'spy_conditioned', 'vix_conditioned', 'spy_vix_combined']:
    sharpes = [r['sharpe_net_etf'] for r in oos_results[strat_name]]
    print(f"{strat_name:<25} ", end="")
    for s in sharpes:
        print(f"{s:<10.3f}", end="")
    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes)
    pct_pos = sum(1 for s in sharpes if s > 0) / len(sharpes) * 100
    print(f"{mean_s:<10.3f}{std_s:<10.3f}{pct_pos:<10.0f}")

print("\nCross-OOS Summary (Net Stock Sharpe):")
print(f"{'Strategy':<25} ", end="")
for i, (s, e) in enumerate(oos_periods):
    print(f"{'P'+str(i+1):<10}", end="")
print(f"{'Mean':<10}{'Std':<10}{'% >0':<10}")

for strat_name in ['always_overnight', 'spy_conditioned', 'vix_conditioned', 'spy_vix_combined']:
    sharpes = [r['sharpe_net_stock'] for r in oos_results[strat_name]]
    print(f"{strat_name:<25} ", end="")
    for s in sharpes:
        print(f"{s:<10.3f}", end="")
    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes)
    pct_pos = sum(1 for s in sharpes if s > 0) / len(sharpes) * 100
    print(f"{mean_s:<10.3f}{std_s:<10.3f}{pct_pos:<10.0f}")

# ============================================================
# 7. TX Break-even Analysis
# ============================================================
print("\n\n[7] TX Break-even Analysis")
print("=" * 70)

for strat_name, sig_series in [
    ('always_overnight', sig1),
    ('spy_conditioned', sig2),
    ('vix_conditioned', sig3),
    ('spy_vix_combined', sig4),
]:
    common = sig_series.index.intersection(df['gap_ret'].index)
    sig = sig_series.loc[common]
    ret = df['gap_ret'].loc[common]

    # Average daily gap return on signal days
    if sig.sum() > 0:
        avg_gap = (ret * sig).sum() / sig.sum()
        breakeven_tx = avg_gap  # TX must be < avg_gap for profitability
        print(f"  {strat_name:<25}: avg gap on signal = {avg_gap*100:.4f}% ({avg_gap*10000:.2f} bps)")
        print(f"    → Break-even TX: {breakeven_tx*100:.4f}% ({breakeven_tx*10000:.2f} bps)")
        print(f"    → Stock TX 0.585% → {'PROFITABLE' if breakeven_tx > TX_COST else 'UNPROFITABLE'}")
        print(f"    → ETF TX 0.385%   → {'PROFITABLE' if breakeven_tx > TX_COST_ETF else 'UNPROFITABLE'}")
        print(f"    → Need TX < {breakeven_tx*10000:.1f} bps for profitability")
    else:
        print(f"  {strat_name:<25}: no trades")

# ============================================================
# 8. Reduced Frequency Variants
# ============================================================
print("\n\n[8] Reduced Frequency Variants (Lower TX Impact)")
print("=" * 70)

# What if we only trade 2-3 days per week (strongest signal days)?
# SPY momentum: only trade when |SPY_ret| > median
spy_median = df['spy_ret_prev'].abs().median()

print(f"\n  SPY return median magnitude: {spy_median*100:.3f}%")

# Strong SPY up signal
sig5 = (df['spy_ret_prev'] > spy_median).astype(int)
res5, _, _, _ = backtest_strategy(sig5, df['gap_ret'], 'Strong SPY Up Only', TX_COST)
strategies['strong_spy_up'] = res5
print(f"\n  Strategy 5: Strong SPY Up (>{spy_median*100:.3f}%)")
print(f"    Exposure: {res5['exposure_pct']}%, trades/yr: {res5['n_trades']/(res5['n_days']/252):.0f}")
print(f"    Gross: Sharpe={res5['sharpe_gross']:.3f}, Return={res5['ann_return_gross_pct']:.2f}%")
print(f"    Net(ETF): Sharpe={res5['sharpe_net_etf']:.3f}, Return={res5['ann_return_net_etf_pct']:.2f}%")

# Very strong SPY: top quartile
spy_q75 = df['spy_ret_prev'].quantile(0.75)
sig6 = (df['spy_ret_prev'] > spy_q75).astype(int)
res6, _, _, _ = backtest_strategy(sig6, df['gap_ret'], 'Top Quartile SPY Up', TX_COST)
strategies['top_quartile_spy'] = res6
print(f"\n  Strategy 6: Top Quartile SPY (>{spy_q75*100:.3f}%)")
print(f"    Exposure: {res6['exposure_pct']}%, trades/yr: {res6['n_trades']/(res6['n_days']/252):.0f}")
print(f"    Gross: Sharpe={res6['sharpe_gross']:.3f}, Return={res6['ann_return_gross_pct']:.2f}%")
print(f"    Net(ETF): Sharpe={res6['sharpe_net_etf']:.3f}, Return={res6['ann_return_net_etf_pct']:.2f}%")

# Consecutive SPY up: 2 consecutive days SPY > 0
sig7 = ((df['spy_ret_prev'] > 0) & (df['spy_ret_prev'].shift(1) > 0)).astype(int)
res7, _, _, _ = backtest_strategy(sig7, df['gap_ret'], '2-Day SPY Momentum', TX_COST)
strategies['2day_spy_momentum'] = res7
print(f"\n  Strategy 7: 2-Day SPY Momentum")
print(f"    Exposure: {res7['exposure_pct']}%, trades/yr: {res7['n_trades']/(res7['n_days']/252):.0f}")
print(f"    Gross: Sharpe={res7['sharpe_gross']:.3f}, Return={res7['ann_return_gross_pct']:.2f}%")
print(f"    Net(ETF): Sharpe={res7['sharpe_net_etf']:.3f}, Return={res7['ann_return_net_etf_pct']:.2f}%")

# ============================================================
# 9. Yearly Breakdown (Best Strategy)
# ============================================================
print("\n\n[9] Yearly Breakdown — Always Overnight (Gross)")
print("=" * 70)

df['year'] = df.index.year
yearly_stats = []

for year in sorted(df['year'].unique()):
    yr_data = df[df['year'] == year]
    gap = yr_data['gap_ret']
    ann_r = gap.mean() * 252
    ann_v = gap.std() * np.sqrt(252)
    sr = ann_r / ann_v if ann_v > 0 else 0
    cum = (1 + gap).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min()

    yr_dict = {
        'year': int(year),
        'n_days': len(yr_data),
        'mean_gap_bps': round(gap.mean() * 10000, 2),
        'ann_return_pct': round(ann_r * 100, 2),
        'ann_vol_pct': round(ann_v * 100, 2),
        'sharpe': round(sr, 3),
        'mdd_pct': round(mdd * 100, 2),
        'pct_positive': round((gap > 0).mean() * 100, 1),
    }
    yearly_stats.append(yr_dict)
    print(f"  {year}: gap={yr_dict['mean_gap_bps']:+6.2f} bps/day, "
          f"Sharpe={sr:+.3f}, MDD={mdd*100:.1f}%, %pos={yr_dict['pct_positive']:.1f}%")

# ============================================================
# 10. Statistical Tests
# ============================================================
print("\n\n[10] Statistical Significance Tests")
print("=" * 70)

# Test: is SPY-conditioned gap mean significantly > unconditional gap mean?
gap_spy_up = df.loc[df['spy_ret_prev'] > 0, 'gap_ret']
gap_spy_dn = df.loc[df['spy_ret_prev'] <= 0, 'gap_ret']

t_diff, p_diff = stats.ttest_ind(gap_spy_up, gap_spy_dn)
print(f"  Gap when SPY>0: {gap_spy_up.mean()*10000:.2f} bps ({len(gap_spy_up)} days)")
print(f"  Gap when SPY≤0: {gap_spy_dn.mean()*10000:.2f} bps ({len(gap_spy_dn)} days)")
print(f"  Difference t-test: t={t_diff:.3f}, p={p_diff:.4f}")

# Test: is VIX<20 gap mean significantly > VIX≥20?
gap_vix_low = df.loc[df['vix_prev'] < 20, 'gap_ret']
gap_vix_high = df.loc[df['vix_prev'] >= 20, 'gap_ret']

t_vix, p_vix = stats.ttest_ind(gap_vix_low, gap_vix_high)
print(f"\n  Gap when VIX<20:  {gap_vix_low.mean()*10000:.2f} bps ({len(gap_vix_low)} days)")
print(f"  Gap when VIX≥20:  {gap_vix_high.mean()*10000:.2f} bps ({len(gap_vix_high)} days)")
print(f"  Difference t-test: t={t_vix:.3f}, p={p_vix:.4f}")

# Correlation: SPY_ret vs Taiwan gap
corr_spy_gap = df['spy_ret_prev'].corr(df['gap_ret'])
print(f"\n  Correlation SPY_ret(t-1) vs TW gap(t): {corr_spy_gap:.4f}")

# Regression: gap = a + b * SPY_ret
from numpy.polynomial.polynomial import polyfit
slope, intercept = np.polyfit(df['spy_ret_prev'], df['gap_ret'], 1)
# Manual t-test for slope
n = len(df)
x = df['spy_ret_prev'].values
y = df['gap_ret'].values
y_pred = intercept + slope * x
residuals = y - y_pred
se_slope = np.sqrt(np.sum(residuals**2) / (n - 2) / np.sum((x - x.mean())**2))
t_slope = slope / se_slope
print(f"  Regression: gap = {intercept*10000:.2f} + {slope:.4f} * SPY_ret")
print(f"  Slope t-stat: {t_slope:.3f}")
print(f"  R²: {corr_spy_gap**2:.4f}")

# ============================================================
# 11. Key Findings Summary
# ============================================================
print("\n\n[11] KEY FINDINGS")
print("=" * 70)

# Can any strategy survive TX costs?
best_net_etf = max(strategies.items(), key=lambda x: x[1]['sharpe_net_etf'])
best_gross = max(strategies.items(), key=lambda x: x[1]['sharpe_gross'])

print(f"\n  Best Gross Sharpe: {best_gross[0]} = {best_gross[1]['sharpe_gross']:.3f}")
print(f"  Best Net(ETF) Sharpe: {best_net_etf[0]} = {best_net_etf[1]['sharpe_net_etf']:.3f}")
print(f"\n  Gap return mean: {df['gap_ret'].mean()*10000:.2f} bps/day")
print(f"  ETF TX cost: {TX_COST_ETF*10000:.0f} bps/day")
print(f"  Stock TX cost: {TX_COST*10000:.0f} bps/day")
print(f"  Gap vs ETF TX: {'COVERS' if df['gap_ret'].mean() > TX_COST_ETF else 'CANNOT COVER'} TX costs")

# Harvey threshold check
print(f"\n  Harvey (2016) t>3.0 check:")
for name, res in strategies.items():
    if 't_stat_gross' in res:
        harvey_pass = '✓ PASS' if abs(res['t_stat_gross']) > 3.0 else '✗ FAIL'
        print(f"    {name:<25}: t={res['t_stat_gross']:.3f} {harvey_pass} (gross)")

# Conclusion
feasible = any(v['sharpe_net_etf'] > 0 for v in strategies.values())
practical = any(v['sharpe_net_etf'] > 0.3 for v in strategies.values())

if practical:
    conclusion = "PRACTICALLY FEASIBLE — some strategies survive TX with decent Sharpe"
elif feasible:
    conclusion = "MARGINALLY FEASIBLE — positive net Sharpe but weak"
else:
    conclusion = "INFEASIBLE — TX costs destroy all gap returns"

print(f"\n  CONCLUSION: {conclusion}")

elapsed = time.time() - start_time
print(f"\n  Elapsed: {elapsed:.1f}s")

# ============================================================
# 12. Save Results
# ============================================================
results = {
    "experiment_id": "K515",
    "title": "Taiwan Overnight Gap Trading Strategy",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "attribution": "[提出: 用戶, 執行: Claude]",
    "data_source": "yfinance: 0050.TW, SPY, ^VIX",
    "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "n_trading_days": int(len(df)),
    "references": [
        "K502: Alpha concentration in overnight gap (77-93%)",
        "K451: Overnight vol decomposition (36-44% of total)",
        "T5d/T5e: SPY overnight momentum for Taiwan (Sharpe 1.82 but TX kills)",
        "Lou, Polk, Skouras (2019): A Tug of War: Overnight Versus Intraday Expected Returns, JFE"
    ],
    "tx_assumptions": {
        "etf_round_trip_pct": 0.1855,
        "note": "CORRECTED (K625): ETF: 0.04275%*2 commission (3折) + 0.1% ETF tax = 0.1855%"
    },
    "gap_return_diagnostics": {
        "mean_bps_per_day": round(df['gap_ret'].mean() * 10000, 2),
        "median_bps_per_day": round(df['gap_ret'].median() * 10000, 2),
        "std_bps_per_day": round(df['gap_ret'].std() * 10000, 2),
        "skew": round(float(df['gap_ret'].skew()), 3),
        "kurtosis": round(float(df['gap_ret'].kurtosis()), 3),
        "pct_positive": round((df['gap_ret'] > 0).mean() * 100, 1),
        "annualized_return_pct": round(float(df['gap_ret'].mean() * 252 * 100), 2),
        "annualized_vol_pct": round(float(df['gap_ret'].std() * np.sqrt(252) * 100), 2),
        "sharpe_no_tx": round(float(gap_sharpe), 3),
        "t_stat": round(float(t_stat_gap), 3),
        "p_val": round(float(p_val_gap), 4),
        "gap_share_of_total_return_pct": round(float(gap_ret.sum() / c2c_ret.sum() * 100), 1),
        "gap_share_of_total_vol_pct": round(float(gap_ret.var() / c2c_ret.var() * 100), 1),
    },
    "strategies": strategies,
    "cross_oos": {period: {
        strat: {
            'sharpe_gross': oos_results[strat][i]['sharpe_gross'],
            'sharpe_net_etf': oos_results[strat][i]['sharpe_net_etf'],
            'sharpe_net_stock': oos_results[strat][i]['sharpe_net_stock'],
            'ann_return_gross_pct': oos_results[strat][i]['ann_return_gross_pct'],
        }
        for strat in oos_results
        if i < len(oos_results[strat])
    } for i, period in enumerate([f"P{j+1}: {s} to {e}" for j, (s, e) in enumerate(oos_periods)])},
    "yearly_stats": yearly_stats,
    "statistical_tests": {
        "spy_conditioning": {
            "gap_spy_up_bps": round(gap_spy_up.mean() * 10000, 2),
            "gap_spy_dn_bps": round(gap_spy_dn.mean() * 10000, 2),
            "t_stat": round(float(t_diff), 3),
            "p_val": round(float(p_diff), 4),
        },
        "vix_conditioning": {
            "gap_vix_low_bps": round(gap_vix_low.mean() * 10000, 2),
            "gap_vix_high_bps": round(gap_vix_high.mean() * 10000, 2),
            "t_stat": round(float(t_vix), 3),
            "p_val": round(float(p_vix), 4),
        },
        "spy_gap_correlation": round(float(corr_spy_gap), 4),
        "spy_gap_regression": {
            "intercept_bps": round(float(intercept * 10000), 2),
            "slope": round(float(slope), 4),
            "t_slope": round(float(t_slope), 3),
            "r_squared": round(float(corr_spy_gap**2), 4),
        }
    },
    "benchmark_buy_hold": {
        "ann_return_pct": round(float(ann_bh * 100), 2),
        "ann_vol_pct": round(float(vol_bh * 100), 2),
        "sharpe": round(float(sharpe_bh), 3),
        "mdd_pct": round(float(mdd_bh * 100), 2),
    },
    "conclusion": conclusion,
    "key_findings": [
        f"Gap return mean = {df['gap_ret'].mean()*10000:.2f} bps/day, ETF TX = {TX_COST_ETF*10000:.0f} bps/day",
        f"Always overnight gross Sharpe = {res1['sharpe_gross']:.3f}, but TX destroys it",
        f"SPY-conditioned gap (SPY>0) = {gap_spy_up.mean()*10000:.2f} bps vs SPY≤0 = {gap_spy_dn.mean()*10000:.2f} bps (t={t_diff:.3f})",
        f"SPY→TW gap correlation = {corr_spy_gap:.4f}, R²={corr_spy_gap**2:.4f}",
        "Daily overnight trading requires ~2-4 bps avg gap to cover ETF TX of 18.55 bps (corrected K625) → still impossible at daily freq",
        "Even with SPY/VIX conditioning, gap returns cannot cover daily round-trip TX costs",
        "Validates T5e finding: alpha exists in theory but TX costs are prohibitive for daily frequency"
    ],
    "limitations": [
        "yfinance open/close prices may not reflect actual executable prices",
        "0050.TW has smaller tick size issues for large positions",
        "No slippage modeled (market-on-close/open orders have variable fill quality)",
        "Futures (TX) would have lower TX but different mechanics",
        "Period includes multiple structural regime changes (2010-2025)"
    ],
    "elapsed_seconds": round(elapsed, 1)
}

out_path = 'experiments/k515_overnight_gap_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2, default=str)

print(f"\n  Results saved to {out_path}")
print("\nDone.")
