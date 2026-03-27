#!/usr/bin/env python3
"""
K517: Monthly Overnight Gap Strategy — 一般投資人版本
=====================================================
[提出: 用戶, 執行: Claude]

Background:
  K515: Overnight gap alpha 10.73bp/day (t=6.845) but ETF TX fatal (38.5bp/day).
  K516: Futures 5bp daily TX → Sharpe 0.93, 5/5 cross-OOS. But requires futures account.
  K516 also found monthly rebalancing Sharpe=0.876 at 10bp.

THIS experiment: Monthly timing strategy for GENERAL investors.
  - NOT daily overnight gap trading (TX too high)
  - Instead: monthly decision — hold 0050.TW this month or cash
  - Signal based on prior-month SPY return and/or month-end VIX
  - TX: only 1 round-trip per month change → 0.585% RT (ETF feasible!)
  - Uses monthly CLOSE-TO-CLOSE returns (not gap returns)

Strategies:
  1. Monthly SPY Signal: prior month SPY > 0 → hold
  2. Monthly VIX Signal: month-end VIX < 20 → hold
  3. Monthly SPY + VIX: SPY > 0 AND VIX < 25 → hold
  4. Monthly SPY + VIX + 12/VIX VT: hold decision by SPY+VIX, weight by 8.63/VIX

Benchmarks:
  - Buy & Hold 0050.TW
  - 8.63/VIX monthly (existing Taiwan VT strategy)

Data: yfinance 0050.TW, SPY, ^VIX
Period: 2010-2025
TX: 0.585% round-trip per monthly trade (ETF bid-ask + commission)
Cross-OOS: 5 periods

References:
  - K515: Taiwan Overnight Gap — alpha real but ETF TX fatal
  - K516: Futures-level TX Sharpe 0.93, monthly rebalancing 0.876
  - K502: 77-93% alpha in overnight gap
  - Lou, Polk, Skouras (2019): "A Tug of War: Overnight vs Intraday Returns", JFE
  - 8.63/VIX Taiwan VT: Sharpe 1.16, MDD -13.4%
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
print("K517: Monthly Overnight Gap Strategy — General Investor Version")
print("=" * 70)

print("\n[1] Downloading data...")
tw50 = yf.download('0050.TW', start='2010-01-01', end='2026-01-01', progress=False)
spy = yf.download('SPY', start='2010-01-01', end='2026-01-01', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-01-01', progress=False)

# Flatten multi-level columns if present
for df_raw in [tw50, spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

print(f"  0050.TW: {len(tw50)} days ({tw50.index[0].strftime('%Y-%m-%d')} to {tw50.index[-1].strftime('%Y-%m-%d')})")
print(f"  SPY:     {len(spy)} days ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX:     {len(vix)} days ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 1b. Fix 0050.TW Stock Split (2014-01-02, 4:1 split)
# ============================================================
# yfinance does NOT properly adjust 0050.TW Close for the 4:1 stock split.
# Pre-split Close ~37-38, post-split ~9-10. Must divide pre-split by 4.
print("\n[1b] Fixing 0050.TW 4:1 stock split (2014-01-02)...")
split_date = pd.Timestamp('2014-01-02')
pre_split_mask = tw50.index < split_date
n_pre = pre_split_mask.sum()
print(f"  Pre-split days: {n_pre}")
tw50.loc[pre_split_mask, 'Close'] = tw50.loc[pre_split_mask, 'Close'] / 4.0
tw50.loc[pre_split_mask, 'Open'] = tw50.loc[pre_split_mask, 'Open'] / 4.0
tw50.loc[pre_split_mask, 'High'] = tw50.loc[pre_split_mask, 'High'] / 4.0
tw50.loc[pre_split_mask, 'Low'] = tw50.loc[pre_split_mask, 'Low'] / 4.0

# Verify fix
idx_split = tw50.index.get_loc(split_date)
prev_close = float(tw50['Close'].iloc[idx_split - 1])
split_close = float(tw50['Close'].iloc[idx_split])
ret_at_split = (split_close - prev_close) / prev_close
print(f"  Pre-split last close (adj): {prev_close:.2f}")
print(f"  Post-split first close: {split_close:.2f}")
print(f"  Return at split: {ret_at_split*100:.2f}% (should be ~0%)")
assert abs(ret_at_split) < 0.05, f"Split adjustment failed: return={ret_at_split:.4f}"

# ============================================================
# 2. Build Monthly Data
# ============================================================
print("\n[2] Building monthly data...")

# Monthly close prices
tw_monthly = tw50['Close'].resample('ME').last().dropna()
spy_monthly = spy['Close'].resample('ME').last().dropna()
vix_monthly = vix['Close'].resample('ME').last().dropna()

# Monthly returns
tw_monthly_ret = tw_monthly.pct_change().dropna()
spy_monthly_ret = spy_monthly.pct_change().dropna()

# Align to common dates
common_months = tw_monthly_ret.index.intersection(spy_monthly_ret.index)
common_months = common_months.intersection(vix_monthly.index)

# Build monthly DataFrame
mdf = pd.DataFrame({
    'tw_ret': tw_monthly_ret.loc[common_months],
    'spy_ret': spy_monthly_ret.loc[common_months],
    'vix': vix_monthly.loc[common_months],
})
mdf = mdf.dropna()

# Prior month signals (avoid look-ahead bias)
mdf['spy_ret_prev'] = mdf['spy_ret'].shift(1)
mdf['vix_prev'] = mdf['vix'].shift(1)  # month-end VIX of prior month
mdf = mdf.dropna()

print(f"  Monthly data: {len(mdf)} months ({mdf.index[0].strftime('%Y-%m')} to {mdf.index[-1].strftime('%Y-%m')})")
print(f"  TW monthly return: mean={mdf['tw_ret'].mean()*100:.2f}%, std={mdf['tw_ret'].std()*100:.2f}%")
print(f"  SPY monthly return: mean={mdf['spy_ret'].mean()*100:.2f}%, std={mdf['spy_ret'].std()*100:.2f}%")
print(f"  VIX month-end: mean={mdf['vix'].mean():.1f}, min={mdf['vix'].min():.1f}, max={mdf['vix'].max():.1f}")

# ============================================================
# 3. Data Diagnostics
# ============================================================
print("\n[3] Data Diagnostics")
print("=" * 70)

for name, series in [('TW monthly ret', mdf['tw_ret']), ('SPY monthly ret', mdf['spy_ret']),
                      ('VIX month-end', mdf['vix'])]:
    print(f"\n  {name}:")
    print(f"    N={len(series)}, Mean={series.mean():.4f}, Std={series.std():.4f}")
    print(f"    Skew={series.skew():.3f}, Kurt={series.kurtosis():.3f}")
    print(f"    Min={series.min():.4f}, Max={series.max():.4f}")

# Correlation matrix
corr_tw_spy = mdf['tw_ret'].corr(mdf['spy_ret_prev'])
corr_tw_vix = mdf['tw_ret'].corr(mdf['vix_prev'])
print(f"\n  Correlation TW_ret vs prior_SPY_ret: {corr_tw_spy:.4f}")
print(f"  Correlation TW_ret vs prior_month_end_VIX: {corr_tw_vix:.4f}")

# Signal effectiveness (conditional means)
spy_up = mdf.loc[mdf['spy_ret_prev'] > 0, 'tw_ret']
spy_dn = mdf.loc[mdf['spy_ret_prev'] <= 0, 'tw_ret']
t_spy, p_spy = stats.ttest_ind(spy_up, spy_dn)
print(f"\n  TW return when prior SPY > 0: {spy_up.mean()*100:.2f}% ({len(spy_up)} months)")
print(f"  TW return when prior SPY ≤ 0: {spy_dn.mean()*100:.2f}% ({len(spy_dn)} months)")
print(f"  Difference t-test: t={t_spy:.3f}, p={p_spy:.4f}")

vix_low = mdf.loc[mdf['vix_prev'] < 20, 'tw_ret']
vix_high = mdf.loc[mdf['vix_prev'] >= 20, 'tw_ret']
t_vix, p_vix = stats.ttest_ind(vix_low, vix_high)
print(f"\n  TW return when prior VIX < 20: {vix_low.mean()*100:.2f}% ({len(vix_low)} months)")
print(f"  TW return when prior VIX ≥ 20: {vix_high.mean()*100:.2f}% ({len(vix_high)} months)")
print(f"  Difference t-test: t={t_vix:.3f}, p={p_vix:.4f}")

# ============================================================
# 4. Strategy Backtesting Functions
# ============================================================

TX_COST = 0.00585  # 0.585% round-trip for Taiwan ETF

def backtest_monthly(signal, tw_ret, name, tx_cost=TX_COST):
    """
    Backtest monthly timing strategy.

    signal: pd.Series of 0/1 (1=hold this month, 0=cash)
    tw_ret: pd.Series of monthly returns for 0050.TW
    tx_cost: round-trip cost per trade (0.585% for ETF)

    TX logic: charged when position changes (enter or exit).
      - Enter: pay tx_cost/2 (buy)
      - Exit: pay tx_cost/2 (sell)
      - Each switch = 1 round-trip = tx_cost
      - First month hold = half (buy only); last month exit = half (sell only)
    """
    common = signal.index.intersection(tw_ret.index)
    sig = signal.loc[common].astype(float)
    ret = tw_ret.loc[common]

    n_months = len(common)
    n_hold = int(sig.sum())
    exposure = n_hold / n_months if n_months > 0 else 0

    # Gross returns
    strat_ret_gross = ret * sig

    # Count position changes for TX
    sig_diff = sig.diff().fillna(sig.iloc[0])  # first value = entering or not
    position_changes = (sig_diff != 0).astype(int)
    # Each position change = half round-trip
    # But enter+exit = full round-trip
    # More precisely: count switches (0→1 or 1→0)
    n_switches = int(position_changes.sum())
    # Each switch costs tx_cost (treated as full round-trip equivalent)
    # Actually: entering costs tx/2 (buy), exiting costs tx/2 (sell)
    # A pair (enter then exit) = 1 full round-trip
    # Count entries and exits separately
    entries = ((sig_diff > 0)).sum()
    exits = ((sig_diff < 0)).sum()
    # If last position is 1, we'll exit eventually (add 1 exit)
    if sig.iloc[-1] > 0:
        exits += 1
    n_round_trips = max(int(entries), int(exits))  # each entry pairs with an exit

    # Distribute TX cost across holding months
    total_tx = n_round_trips * tx_cost
    if n_hold > 0:
        tx_per_month = total_tx / n_hold
    else:
        tx_per_month = 0

    strat_ret_net = strat_ret_gross.copy()
    strat_ret_net[sig > 0] -= tx_per_month

    # Metrics - Gross
    ann_ret_gross = float(strat_ret_gross.mean() * 12)
    ann_vol_gross = float(strat_ret_gross.std() * np.sqrt(12))
    sharpe_gross = ann_ret_gross / ann_vol_gross if ann_vol_gross > 0 else 0

    cum_gross = (1 + strat_ret_gross).cumprod()
    total_ret_gross = float(cum_gross.iloc[-1] - 1)
    mdd_gross = float(((cum_gross - cum_gross.cummax()) / cum_gross.cummax()).min())

    # T-stat (Harvey threshold = 3.0)
    trading_months = strat_ret_gross[sig > 0]
    if len(trading_months) > 10:
        t_gross, p_gross = stats.ttest_1samp(trading_months, 0)
        t_gross = float(t_gross)
        p_gross = float(p_gross)
    else:
        t_gross, p_gross = 0.0, 1.0

    # Metrics - Net
    ann_ret_net = float(strat_ret_net.mean() * 12)
    ann_vol_net = float(strat_ret_net.std() * np.sqrt(12))
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 0 else 0

    cum_net = (1 + strat_ret_net).cumprod()
    total_ret_net = float(cum_net.iloc[-1] - 1)
    mdd_net = float(((cum_net - cum_net.cummax()) / cum_net.cummax()).min())

    # Net t-stat
    trading_months_net = strat_ret_net[sig > 0]
    if len(trading_months_net) > 10:
        t_net, p_net = stats.ttest_1samp(trading_months_net, 0)
        t_net = float(t_net)
        p_net = float(p_net)
    else:
        t_net, p_net = 0.0, 1.0

    # Win rates
    win_rate_gross = float((trading_months > 0).mean()) if len(trading_months) > 0 else 0
    win_rate_net = float((trading_months_net > 0).mean()) if len(trading_months_net) > 0 else 0

    # Calmar & Sortino
    calmar_net = ann_ret_net / abs(mdd_net) if mdd_net != 0 else 0
    downside = strat_ret_net[strat_ret_net < 0]
    downside_vol = float(downside.std() * np.sqrt(12)) if len(downside) > 0 else 1
    sortino_net = ann_ret_net / downside_vol if downside_vol > 0 else 0

    # CAGR
    n_years = n_months / 12
    cagr_gross = float((cum_gross.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 and cum_gross.iloc[-1] > 0 else 0
    cagr_net = float((cum_net.iloc[-1]) ** (1 / n_years) - 1) if n_years > 0 and cum_net.iloc[-1] > 0 else 0

    # Avg return conditional on signal
    avg_ret_hold = float(ret[sig > 0].mean()) if (sig > 0).sum() > 0 else 0
    avg_ret_cash = float(ret[sig <= 0].mean()) if (sig <= 0).sum() > 0 else 0

    return {
        'name': name,
        'n_months': n_months,
        'n_hold_months': n_hold,
        'n_cash_months': n_months - n_hold,
        'exposure_pct': round(exposure * 100, 1),
        'n_round_trips': n_round_trips,
        'tx_per_month_pct': round(tx_per_month * 100, 3),
        'total_tx_pct': round(total_tx * 100, 2),
        'avg_ret_hold_pct': round(avg_ret_hold * 100, 2),
        'avg_ret_cash_pct': round(avg_ret_cash * 100, 2),
        'win_rate_gross_pct': round(win_rate_gross * 100, 1),
        'win_rate_net_pct': round(win_rate_net * 100, 1),
        'ann_return_gross_pct': round(ann_ret_gross * 100, 2),
        'ann_vol_gross_pct': round(ann_vol_gross * 100, 2),
        'sharpe_gross': round(sharpe_gross, 3),
        'total_return_gross_pct': round(total_ret_gross * 100, 2),
        'cagr_gross_pct': round(cagr_gross * 100, 2),
        'mdd_gross_pct': round(mdd_gross * 100, 2),
        't_stat_gross': round(t_gross, 3),
        'p_val_gross': round(p_gross, 4),
        'ann_return_net_pct': round(ann_ret_net * 100, 2),
        'ann_vol_net_pct': round(ann_vol_net * 100, 2),
        'sharpe_net': round(sharpe_net, 3),
        'total_return_net_pct': round(total_ret_net * 100, 2),
        'cagr_net_pct': round(cagr_net * 100, 2),
        'mdd_net_pct': round(mdd_net * 100, 2),
        't_stat_net': round(t_net, 3),
        'p_val_net': round(p_net, 4),
        'calmar_net': round(calmar_net, 3),
        'sortino_net': round(sortino_net, 3),
        'cum_gross': cum_gross,
        'cum_net': cum_net,
        'strat_ret_net': strat_ret_net,
        'signal': sig,
    }


def backtest_vt_monthly(vix_series, tw_ret, name, target_vol_ratio=8.63, tx_cost=TX_COST):
    """
    Backtest 8.63/VIX monthly VT strategy (benchmark).
    weight = min(target_vol_ratio / VIX, 1.5) → position in 0050.TW
    Rebalance monthly. TX on weight change.
    """
    common = vix_series.index.intersection(tw_ret.index)
    vix_vals = vix_series.loc[common]
    ret = tw_ret.loc[common]

    weights = np.minimum(target_vol_ratio / vix_vals, 1.5)
    weights = weights.clip(0, 1.5)

    strat_ret_gross = ret * weights

    # TX: proportional to weight change
    weight_change = weights.diff().fillna(weights.iloc[0]).abs()
    tx_series = weight_change * tx_cost
    strat_ret_net = strat_ret_gross - tx_series

    n_months = len(common)
    n_years = n_months / 12

    ann_ret_gross = float(strat_ret_gross.mean() * 12)
    ann_vol_gross = float(strat_ret_gross.std() * np.sqrt(12))
    sharpe_gross = ann_ret_gross / ann_vol_gross if ann_vol_gross > 0 else 0

    ann_ret_net = float(strat_ret_net.mean() * 12)
    ann_vol_net = float(strat_ret_net.std() * np.sqrt(12))
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 0 else 0

    cum_gross = (1 + strat_ret_gross).cumprod()
    cum_net = (1 + strat_ret_net).cumprod()
    total_ret_gross = float(cum_gross.iloc[-1] - 1)
    total_ret_net = float(cum_net.iloc[-1] - 1)
    mdd_gross = float(((cum_gross - cum_gross.cummax()) / cum_gross.cummax()).min())
    mdd_net = float(((cum_net - cum_net.cummax()) / cum_net.cummax()).min())

    cagr_gross = float(cum_gross.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 and cum_gross.iloc[-1] > 0 else 0
    cagr_net = float(cum_net.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 and cum_net.iloc[-1] > 0 else 0

    # T-stat on net returns
    if len(strat_ret_net) > 10:
        t_net, p_net = stats.ttest_1samp(strat_ret_net, 0)
    else:
        t_net, p_net = 0.0, 1.0

    total_tx_pct = float(tx_series.sum() * 100)
    avg_weight = float(weights.mean())

    calmar_net = ann_ret_net / abs(mdd_net) if mdd_net != 0 else 0
    downside = strat_ret_net[strat_ret_net < 0]
    downside_vol = float(downside.std() * np.sqrt(12)) if len(downside) > 0 else 1
    sortino_net = ann_ret_net / downside_vol if downside_vol > 0 else 0

    return {
        'name': name,
        'n_months': n_months,
        'avg_weight': round(avg_weight, 3),
        'total_tx_pct': round(total_tx_pct, 2),
        'ann_return_gross_pct': round(ann_ret_gross * 100, 2),
        'ann_vol_gross_pct': round(ann_vol_gross * 100, 2),
        'sharpe_gross': round(sharpe_gross, 3),
        'total_return_gross_pct': round(total_ret_gross * 100, 2),
        'cagr_gross_pct': round(cagr_gross * 100, 2),
        'mdd_gross_pct': round(mdd_gross * 100, 2),
        'ann_return_net_pct': round(ann_ret_net * 100, 2),
        'ann_vol_net_pct': round(ann_vol_net * 100, 2),
        'sharpe_net': round(sharpe_net, 3),
        'total_return_net_pct': round(total_ret_net * 100, 2),
        'cagr_net_pct': round(cagr_net * 100, 2),
        'mdd_net_pct': round(mdd_net * 100, 2),
        't_stat_net': round(float(t_net), 3),
        'p_val_net': round(float(p_net), 4),
        'calmar_net': round(calmar_net, 3),
        'sortino_net': round(sortino_net, 3),
        'cum_gross': cum_gross,
        'cum_net': cum_net,
        'strat_ret_net': strat_ret_net,
    }


def backtest_vt_overlay(signal, vix_series, tw_ret, name, target_vol_ratio=8.63, tx_cost=TX_COST):
    """
    Strategy 4: SPY+VIX signal for timing, 8.63/VIX for position sizing.
    When signal=0 → cash. When signal=1 → weight = min(8.63/VIX, 1.5).
    """
    common = signal.index.intersection(tw_ret.index).intersection(vix_series.index)
    sig = signal.loc[common].astype(float)
    vix_vals = vix_series.loc[common]
    ret = tw_ret.loc[common]

    # VT weight only when signal active
    vt_weights = np.minimum(target_vol_ratio / vix_vals, 1.5).clip(0, 1.5)
    weights = vt_weights * sig

    strat_ret_gross = ret * weights

    # TX: proportional to weight change
    weight_change = weights.diff().fillna(weights.iloc[0]).abs()
    tx_series = weight_change * tx_cost
    strat_ret_net = strat_ret_gross - tx_series

    n_months = len(common)
    n_hold = int((sig > 0).sum())
    n_years = n_months / 12
    exposure = n_hold / n_months if n_months > 0 else 0

    ann_ret_gross = float(strat_ret_gross.mean() * 12)
    ann_vol_gross = float(strat_ret_gross.std() * np.sqrt(12))
    sharpe_gross = ann_ret_gross / ann_vol_gross if ann_vol_gross > 0 else 0

    ann_ret_net = float(strat_ret_net.mean() * 12)
    ann_vol_net = float(strat_ret_net.std() * np.sqrt(12))
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 0 else 0

    cum_gross = (1 + strat_ret_gross).cumprod()
    cum_net = (1 + strat_ret_net).cumprod()
    total_ret_gross = float(cum_gross.iloc[-1] - 1)
    total_ret_net = float(cum_net.iloc[-1] - 1)
    mdd_gross = float(((cum_gross - cum_gross.cummax()) / cum_gross.cummax()).min())
    mdd_net = float(((cum_net - cum_net.cummax()) / cum_net.cummax()).min())

    cagr_gross = float(cum_gross.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 and cum_gross.iloc[-1] > 0 else 0
    cagr_net = float(cum_net.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 and cum_net.iloc[-1] > 0 else 0

    if len(strat_ret_net) > 10:
        t_net, p_net = stats.ttest_1samp(strat_ret_net[sig > 0], 0)
    else:
        t_net, p_net = 0.0, 1.0

    total_tx_pct = float(tx_series.sum() * 100)
    avg_weight_active = float(weights[sig > 0].mean()) if n_hold > 0 else 0

    calmar_net = ann_ret_net / abs(mdd_net) if mdd_net != 0 else 0
    downside = strat_ret_net[strat_ret_net < 0]
    downside_vol = float(downside.std() * np.sqrt(12)) if len(downside) > 0 else 1
    sortino_net = ann_ret_net / downside_vol if downside_vol > 0 else 0

    win_rate = float((strat_ret_net[sig > 0] > 0).mean()) if n_hold > 0 else 0

    return {
        'name': name,
        'n_months': n_months,
        'n_hold_months': n_hold,
        'exposure_pct': round(exposure * 100, 1),
        'avg_weight_active': round(avg_weight_active, 3),
        'total_tx_pct': round(total_tx_pct, 2),
        'win_rate_net_pct': round(win_rate * 100, 1),
        'ann_return_gross_pct': round(ann_ret_gross * 100, 2),
        'ann_vol_gross_pct': round(ann_vol_gross * 100, 2),
        'sharpe_gross': round(sharpe_gross, 3),
        'total_return_gross_pct': round(total_ret_gross * 100, 2),
        'cagr_gross_pct': round(cagr_gross * 100, 2),
        'mdd_gross_pct': round(mdd_gross * 100, 2),
        'ann_return_net_pct': round(ann_ret_net * 100, 2),
        'ann_vol_net_pct': round(ann_vol_net * 100, 2),
        'sharpe_net': round(sharpe_net, 3),
        'total_return_net_pct': round(total_ret_net * 100, 2),
        'cagr_net_pct': round(cagr_net * 100, 2),
        'mdd_net_pct': round(mdd_net * 100, 2),
        't_stat_net': round(float(t_net), 3),
        'p_val_net': round(float(p_net), 4),
        'calmar_net': round(calmar_net, 3),
        'sortino_net': round(sortino_net, 3),
        'cum_gross': cum_gross,
        'cum_net': cum_net,
        'strat_ret_net': strat_ret_net,
        'signal': sig,
    }


# ============================================================
# 5. Define Signals and Run Backtests
# ============================================================
print("\n[4] Strategy Backtests (Full Sample)")
print("=" * 70)

# Signal definitions
signals = {
    'spy_signal': (mdf['spy_ret_prev'] > 0).astype(int),
    'vix_signal': (mdf['vix_prev'] < 20).astype(int),
    'spy_vix_signal': ((mdf['spy_ret_prev'] > 0) & (mdf['vix_prev'] < 25)).astype(int),
}

signal_names = {
    'spy_signal': 'Strategy 1: Monthly SPY Signal (SPY>0 → hold)',
    'vix_signal': 'Strategy 2: Monthly VIX Signal (VIX<20 → hold)',
    'spy_vix_signal': 'Strategy 3: Monthly SPY+VIX (SPY>0 & VIX<25 → hold)',
}

results = {}
for key, sig in signals.items():
    res = backtest_monthly(sig, mdf['tw_ret'], signal_names[key])
    results[key] = res

    print(f"\n--- {signal_names[key]} ---")
    print(f"  Exposure: {res['exposure_pct']}% ({res['n_hold_months']}/{res['n_months']} months)")
    print(f"  Round-trips: {res['n_round_trips']}, Total TX: {res['total_tx_pct']:.2f}%")
    print(f"  Avg return (hold months): {res['avg_ret_hold_pct']:.2f}%")
    print(f"  Avg return (cash months): {res['avg_ret_cash_pct']:.2f}%")
    print(f"  Win rate (net): {res['win_rate_net_pct']:.1f}%")
    print(f"  Gross: Sharpe={res['sharpe_gross']:.3f}, Return={res['ann_return_gross_pct']:.2f}%, MDD={res['mdd_gross_pct']:.2f}%")
    print(f"  Net:   Sharpe={res['sharpe_net']:.3f}, Return={res['ann_return_net_pct']:.2f}%, MDD={res['mdd_net_pct']:.2f}%")
    print(f"  CAGR (net): {res['cagr_net_pct']:.2f}%")
    print(f"  t-stat (net): {res['t_stat_net']:.3f} (Harvey threshold: 3.0)")
    print(f"  Calmar={res['calmar_net']:.3f}, Sortino={res['sortino_net']:.3f}")

# Strategy 4: SPY+VIX with VT overlay
print(f"\n--- Strategy 4: Monthly SPY+VIX + 8.63/VIX VT Overlay ---")
res_vt_overlay = backtest_vt_overlay(
    signals['spy_vix_signal'],
    mdf['vix_prev'],
    mdf['tw_ret'],
    'Strategy 4: SPY+VIX + 8.63/VIX VT'
)
results['spy_vix_vt'] = res_vt_overlay
print(f"  Exposure: {res_vt_overlay['exposure_pct']}%, Avg weight (active): {res_vt_overlay['avg_weight_active']:.3f}")
print(f"  Total TX: {res_vt_overlay['total_tx_pct']:.2f}%")
print(f"  Win rate (net): {res_vt_overlay['win_rate_net_pct']:.1f}%")
print(f"  Gross: Sharpe={res_vt_overlay['sharpe_gross']:.3f}, Return={res_vt_overlay['ann_return_gross_pct']:.2f}%, MDD={res_vt_overlay['mdd_gross_pct']:.2f}%")
print(f"  Net:   Sharpe={res_vt_overlay['sharpe_net']:.3f}, Return={res_vt_overlay['ann_return_net_pct']:.2f}%, MDD={res_vt_overlay['mdd_net_pct']:.2f}%")
print(f"  CAGR (net): {res_vt_overlay['cagr_net_pct']:.2f}%")
print(f"  t-stat (net): {res_vt_overlay['t_stat_net']:.3f}")
print(f"  Calmar={res_vt_overlay['calmar_net']:.3f}, Sortino={res_vt_overlay['sortino_net']:.3f}")

# ============================================================
# 6. Benchmarks
# ============================================================
print("\n\n[5] Benchmarks")
print("=" * 70)

# Buy & Hold 0050.TW
bh_ret = mdf['tw_ret']
ann_bh = float(bh_ret.mean() * 12)
vol_bh = float(bh_ret.std() * np.sqrt(12))
sharpe_bh = ann_bh / vol_bh if vol_bh > 0 else 0
cum_bh = (1 + bh_ret).cumprod()
total_ret_bh = float(cum_bh.iloc[-1] - 1)
mdd_bh = float(((cum_bh - cum_bh.cummax()) / cum_bh.cummax()).min())
cagr_bh = float(cum_bh.iloc[-1] ** (1 / (len(bh_ret) / 12)) - 1)
t_bh, p_bh = stats.ttest_1samp(bh_ret, 0)

bh_result = {
    'name': 'Buy & Hold 0050.TW',
    'n_months': len(bh_ret),
    'ann_return_pct': round(ann_bh * 100, 2),
    'ann_vol_pct': round(vol_bh * 100, 2),
    'sharpe': round(sharpe_bh, 3),
    'total_return_pct': round(total_ret_bh * 100, 2),
    'cagr_pct': round(cagr_bh * 100, 2),
    'mdd_pct': round(mdd_bh * 100, 2),
    't_stat': round(float(t_bh), 3),
    'p_val': round(float(p_bh), 4),
}

print(f"\n--- Buy & Hold 0050.TW ---")
print(f"  Ann Return: {ann_bh*100:.2f}%, Vol: {vol_bh*100:.2f}%, Sharpe: {sharpe_bh:.3f}")
print(f"  Total Return: {total_ret_bh*100:.2f}%, CAGR: {cagr_bh*100:.2f}%, MDD: {mdd_bh*100:.2f}%")
print(f"  t-stat: {t_bh:.3f}")

# 8.63/VIX monthly VT (existing strategy)
res_vt = backtest_vt_monthly(mdf['vix_prev'], mdf['tw_ret'], '8.63/VIX Monthly VT')
results['vt_863'] = res_vt

print(f"\n--- 8.63/VIX Monthly VT (Existing Strategy) ---")
print(f"  Avg weight: {res_vt['avg_weight']:.3f}")
print(f"  Total TX: {res_vt['total_tx_pct']:.2f}%")
print(f"  Gross: Sharpe={res_vt['sharpe_gross']:.3f}, Return={res_vt['ann_return_gross_pct']:.2f}%, MDD={res_vt['mdd_gross_pct']:.2f}%")
print(f"  Net:   Sharpe={res_vt['sharpe_net']:.3f}, Return={res_vt['ann_return_net_pct']:.2f}%, MDD={res_vt['mdd_net_pct']:.2f}%")
print(f"  CAGR (net): {res_vt['cagr_net_pct']:.2f}%")
print(f"  t-stat (net): {res_vt['t_stat_net']:.3f}")
print(f"  Calmar={res_vt['calmar_net']:.3f}, Sortino={res_vt['sortino_net']:.3f}")

# ============================================================
# 7. Strategy Comparison Table
# ============================================================
print("\n\n[6] Strategy Comparison Table")
print("=" * 70)
print(f"  {'Strategy':<45} {'Sharpe(N)':<10} {'Return(N)':<10} {'MDD(N)':<10} {'CAGR(N)':<10} {'t-stat':<8} {'Calmar':<8} {'Sortino':<8}")
print(f"  {'='*45} {'='*10} {'='*10} {'='*10} {'='*10} {'='*8} {'='*8} {'='*8}")

for key in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    r = results[key]
    name = r['name'][:44]
    print(f"  {name:<45} {r['sharpe_net']:<10.3f} {r['ann_return_net_pct']:<10.2f} {r['mdd_net_pct']:<10.2f} "
          f"{r['cagr_net_pct']:<10.2f} {r.get('t_stat_net',0):<8.3f} {r['calmar_net']:<8.3f} {r['sortino_net']:<8.3f}")

# Buy & Hold row
print(f"  {'Buy & Hold 0050.TW':<45} {bh_result['sharpe']:<10.3f} {bh_result['ann_return_pct']:<10.2f} {bh_result['mdd_pct']:<10.2f} "
      f"{bh_result['cagr_pct']:<10.2f} {bh_result['t_stat']:<8.3f} {'N/A':<8} {'N/A':<8}")

# ============================================================
# 8. Cross-OOS Validation (5 periods)
# ============================================================
print("\n\n[7] Cross-OOS Validation (5 periods)")
print("=" * 70)

oos_periods = [
    ('2011-06', '2014-05'),  # ~3 years
    ('2014-06', '2017-05'),  # ~3 years
    ('2017-06', '2019-12'),  # ~2.5 years
    ('2020-01', '2022-06'),  # ~2.5 years (includes COVID)
    ('2022-07', '2025-12'),  # ~3.5 years
]

signal_funcs = {
    'spy_signal': lambda d: (d['spy_ret_prev'] > 0).astype(int),
    'vix_signal': lambda d: (d['vix_prev'] < 20).astype(int),
    'spy_vix_signal': lambda d: ((d['spy_ret_prev'] > 0) & (d['vix_prev'] < 25)).astype(int),
}

oos_results = {}
for strat_name, sig_func in signal_funcs.items():
    oos_results[strat_name] = []
    for i, (start, end) in enumerate(oos_periods):
        sub = mdf.loc[start:end]
        if len(sub) < 6:
            continue
        sig = sig_func(sub)
        res_oos = backtest_monthly(sig, sub['tw_ret'], strat_name)
        res_oos['oos_period'] = f"{start} to {end}"
        res_oos['oos_n_months'] = len(sub)
        oos_results[strat_name].append(res_oos)

# Strategy 4 OOS
oos_results['spy_vix_vt'] = []
for i, (start, end) in enumerate(oos_periods):
    sub = mdf.loc[start:end]
    if len(sub) < 6:
        continue
    sig = signal_funcs['spy_vix_signal'](sub)
    res_oos = backtest_vt_overlay(sig, sub['vix_prev'], sub['tw_ret'], 'spy_vix_vt')
    res_oos['oos_period'] = f"{start} to {end}"
    res_oos['oos_n_months'] = len(sub)
    oos_results['spy_vix_vt'].append(res_oos)

# VT benchmark OOS
oos_results['vt_863'] = []
for i, (start, end) in enumerate(oos_periods):
    sub = mdf.loc[start:end]
    if len(sub) < 6:
        continue
    res_oos = backtest_vt_monthly(sub['vix_prev'], sub['tw_ret'], 'vt_863')
    res_oos['oos_period'] = f"{start} to {end}"
    res_oos['oos_n_months'] = len(sub)
    oos_results['vt_863'].append(res_oos)

# Print OOS results
print("\nCross-OOS Net Sharpe:")
print(f"  {'Strategy':<35} ", end="")
for i in range(len(oos_periods)):
    print(f"{'P'+str(i+1):<9}", end="")
print(f"{'Mean':<9}{'Std':<9}{'#>0':<6}{'#>BH':<6}")

for strat_name in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    if strat_name not in oos_results or len(oos_results[strat_name]) == 0:
        continue
    sharpes = [r['sharpe_net'] for r in oos_results[strat_name]]

    # Compare with B&H per period
    bh_sharpes = []
    for i, (start, end) in enumerate(oos_periods):
        sub = mdf.loc[start:end]
        if len(sub) >= 6:
            bh_ann = float(sub['tw_ret'].mean() * 12)
            bh_vol = float(sub['tw_ret'].std() * np.sqrt(12))
            bh_s = bh_ann / bh_vol if bh_vol > 0 else 0
            bh_sharpes.append(bh_s)

    name_short = strat_name[:34]
    print(f"  {name_short:<35} ", end="")
    n_beat_bh = 0
    for i, s in enumerate(sharpes):
        print(f"{s:<9.3f}", end="")
        if i < len(bh_sharpes) and s > bh_sharpes[i]:
            n_beat_bh += 1
    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes)
    n_pos = sum(1 for s in sharpes if s > 0)
    print(f"{mean_s:<9.3f}{std_s:<9.3f}{n_pos}/{len(sharpes):<4} {n_beat_bh}/{len(bh_sharpes)}")

# Print B&H OOS Sharpe for reference
bh_sharpes_all = []
print(f"\n  {'Buy & Hold 0050.TW':<35} ", end="")
for i, (start, end) in enumerate(oos_periods):
    sub = mdf.loc[start:end]
    if len(sub) >= 6:
        bh_ann = float(sub['tw_ret'].mean() * 12)
        bh_vol = float(sub['tw_ret'].std() * np.sqrt(12))
        bh_s = bh_ann / bh_vol if bh_vol > 0 else 0
        bh_sharpes_all.append(bh_s)
        print(f"{bh_s:<9.3f}", end="")
print(f"{np.mean(bh_sharpes_all):<9.3f}{np.std(bh_sharpes_all):<9.3f}")

# ============================================================
# 9. Cross-OOS MDD comparison
# ============================================================
print("\nCross-OOS Net MDD:")
print(f"  {'Strategy':<35} ", end="")
for i in range(len(oos_periods)):
    print(f"{'P'+str(i+1):<9}", end="")
print(f"{'Mean':<9}")

for strat_name in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    if strat_name not in oos_results or len(oos_results[strat_name]) == 0:
        continue
    mdds = [r['mdd_net_pct'] for r in oos_results[strat_name]]
    print(f"  {strat_name[:34]:<35} ", end="")
    for m in mdds:
        print(f"{m:<9.1f}", end="")
    print(f"{np.mean(mdds):<9.1f}")

# B&H MDD
print(f"  {'Buy & Hold':<35} ", end="")
for i, (start, end) in enumerate(oos_periods):
    sub = mdf.loc[start:end]
    if len(sub) >= 6:
        cum_sub = (1 + sub['tw_ret']).cumprod()
        mdd_sub = float(((cum_sub - cum_sub.cummax()) / cum_sub.cummax()).min() * 100)
        print(f"{mdd_sub:<9.1f}", end="")
print()

# ============================================================
# 10. DM Test: Strategy vs Buy & Hold
# ============================================================
print("\n\n[8] Diebold-Mariano Tests vs Buy & Hold")
print("=" * 70)

bh_monthly_ret = mdf['tw_ret']

dm_results = {}
for strat_name in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    r = results[strat_name]
    strat_net = r['strat_ret_net']

    # Align
    common = strat_net.index.intersection(bh_monthly_ret.index)
    s_ret = strat_net.loc[common]
    b_ret = bh_monthly_ret.loc[common]

    # Loss differential (using squared return as proxy for utility)
    # More meaningful: compare risk-adjusted returns
    # Simple DM: d_t = R_strat_t - R_bh_t
    d = s_ret - b_ret
    mean_d = float(d.mean())
    std_d = float(d.std())
    n = len(d)

    if std_d > 0 and n > 10:
        # Newey-West adjusted standard error (1 lag for monthly)
        from statsmodels.stats.stattools import durbin_watson
        # Simple t-stat (no NW for simplicity given monthly data)
        dm_t = mean_d / (std_d / np.sqrt(n))
        dm_p = 2 * (1 - stats.t.cdf(abs(dm_t), n - 1))
    else:
        dm_t, dm_p = 0.0, 1.0

    dm_results[strat_name] = {
        'mean_excess_return_pct': round(mean_d * 100, 3),
        'dm_t': round(dm_t, 3),
        'dm_p': round(dm_p, 4),
        'beats_bh': dm_t > 0,
        'significant_5pct': dm_p < 0.05,
        'harvey_pass': abs(dm_t) > 3.0,
    }

    print(f"\n  {r['name'][:50]} vs B&H:")
    print(f"    Mean excess return: {mean_d*100:.3f}%/month")
    print(f"    DM t-stat: {dm_t:.3f} (p={dm_p:.4f})")
    print(f"    Harvey t>3.0: {'PASS' if abs(dm_t) > 3.0 else 'FAIL'}")

# ============================================================
# 11. Yearly Breakdown (Best Strategy)
# ============================================================
print("\n\n[9] Yearly Breakdown")
print("=" * 70)

# Determine which strategy is "best" by net Sharpe
best_key = max(['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt'],
               key=lambda k: results[k]['sharpe_net'])
best_name = results[best_key]['name']
print(f"  Showing yearly breakdown for best strategy: {best_name}")
print(f"  And benchmarks: 8.63/VIX VT, Buy & Hold\n")

# Build yearly returns
mdf['year'] = mdf.index.year
years = sorted(mdf['year'].unique())

yearly_data = []
for year in years:
    year_data = mdf[mdf['year'] == year]
    if len(year_data) < 3:
        continue

    # Best strategy
    sig_best = signal_funcs[best_key](year_data) if best_key in signal_funcs else signals[best_key].loc[year_data.index]
    res_y = backtest_monthly(sig_best, year_data['tw_ret'], best_key)

    # VT benchmark
    res_vt_y = backtest_vt_monthly(year_data['vix_prev'], year_data['tw_ret'], 'vt_863')

    # B&H
    cum_bh_y = (1 + year_data['tw_ret']).cumprod()
    ret_bh_y = float(cum_bh_y.iloc[-1] - 1)

    yearly_data.append({
        'year': year,
        'best_net_return_pct': res_y['ann_return_net_pct'],
        'vt_net_return_pct': res_vt_y['ann_return_net_pct'],
        'bh_return_pct': round(ret_bh_y * 100, 2),
        'n_months': len(year_data),
        'best_n_hold': res_y['n_hold_months'],
    })

print(f"  {'Year':<6} {'Best Net%':<12} {'VT Net%':<12} {'B&H%':<12} {'Months':<8} {'Hold':<6}")
print(f"  {'='*6} {'='*12} {'='*12} {'='*12} {'='*8} {'='*6}")
for yd in yearly_data:
    print(f"  {yd['year']:<6} {yd['best_net_return_pct']:<12.2f} {yd['vt_net_return_pct']:<12.2f} "
          f"{yd['bh_return_pct']:<12.2f} {yd['n_months']:<8} {yd['best_n_hold']:<6}")

# ============================================================
# 12. Alternative VIX Thresholds Sensitivity
# ============================================================
print("\n\n[10] VIX Threshold Sensitivity Analysis")
print("=" * 70)

vix_thresholds = [15, 17.5, 20, 22.5, 25, 27.5, 30]
sensitivity_results = []

for vix_thresh in vix_thresholds:
    sig = ((mdf['spy_ret_prev'] > 0) & (mdf['vix_prev'] < vix_thresh)).astype(int)
    res = backtest_monthly(sig, mdf['tw_ret'], f'SPY>0 & VIX<{vix_thresh}')
    sensitivity_results.append({
        'vix_threshold': vix_thresh,
        'exposure_pct': res['exposure_pct'],
        'sharpe_net': res['sharpe_net'],
        'ann_return_net_pct': res['ann_return_net_pct'],
        'mdd_net_pct': res['mdd_net_pct'],
        'cagr_net_pct': res['cagr_net_pct'],
        't_stat_net': res['t_stat_net'],
    })
    print(f"  VIX<{vix_thresh:<5}: Exposure={res['exposure_pct']:.1f}%, "
          f"Sharpe={res['sharpe_net']:.3f}, Return={res['ann_return_net_pct']:.2f}%, "
          f"MDD={res['mdd_net_pct']:.2f}%, t={res['t_stat_net']:.3f}")

# Also test SPY-only thresholds
print("\n  SPY return thresholds (no VIX filter):")
spy_thresholds = [-0.02, -0.01, 0, 0.01, 0.02, 0.03]
spy_sens = []
for spy_thresh in spy_thresholds:
    sig = (mdf['spy_ret_prev'] > spy_thresh).astype(int)
    res = backtest_monthly(sig, mdf['tw_ret'], f'SPY>{spy_thresh*100:.0f}%')
    spy_sens.append({
        'spy_threshold': spy_thresh,
        'exposure_pct': res['exposure_pct'],
        'sharpe_net': res['sharpe_net'],
        'ann_return_net_pct': res['ann_return_net_pct'],
        'mdd_net_pct': res['mdd_net_pct'],
    })
    print(f"  SPY>{spy_thresh*100:+.0f}%: Exposure={res['exposure_pct']:.1f}%, "
          f"Sharpe={res['sharpe_net']:.3f}, Return={res['ann_return_net_pct']:.2f}%, "
          f"MDD={res['mdd_net_pct']:.2f}%")

# ============================================================
# 13. Comparison vs 8.63/VIX: Does adding SPY signal help?
# ============================================================
print("\n\n[11] Does SPY Signal Add Value Over 8.63/VIX?")
print("=" * 70)

# Strategy comparison: spy_vix_vt vs vt_863
r_new = results['spy_vix_vt']
r_old = results['vt_863']

print(f"  8.63/VIX (existing):  Sharpe={r_old['sharpe_net']:.3f}, Return={r_old['ann_return_net_pct']:.2f}%, MDD={r_old['mdd_net_pct']:.2f}%")
print(f"  SPY+VIX+VT (new):    Sharpe={r_new['sharpe_net']:.3f}, Return={r_new['ann_return_net_pct']:.2f}%, MDD={r_new['mdd_net_pct']:.2f}%")

# DM test between strategies
common = r_new['strat_ret_net'].index.intersection(r_old['strat_ret_net'].index)
d_strats = r_new['strat_ret_net'].loc[common] - r_old['strat_ret_net'].loc[common]
dm_t_strats = float(d_strats.mean() / (d_strats.std() / np.sqrt(len(d_strats))))
dm_p_strats = float(2 * (1 - stats.t.cdf(abs(dm_t_strats), len(d_strats) - 1)))
print(f"  DM test (new vs old): t={dm_t_strats:.3f}, p={dm_p_strats:.4f}")
print(f"  Significant at 5%: {'YES' if dm_p_strats < 0.05 else 'NO'}")
print(f"  Harvey t>3.0: {'PASS' if abs(dm_t_strats) > 3.0 else 'FAIL'}")

# All strategies vs VT
print(f"\n  All strategies vs 8.63/VIX:")
for key in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt']:
    r = results[key]
    common = r['strat_ret_net'].index.intersection(r_old['strat_ret_net'].index)
    d = r['strat_ret_net'].loc[common] - r_old['strat_ret_net'].loc[common]
    if d.std() > 0:
        dm_t = float(d.mean() / (d.std() / np.sqrt(len(d))))
        dm_p = float(2 * (1 - stats.t.cdf(abs(dm_t), len(d) - 1)))
    else:
        dm_t, dm_p = 0.0, 1.0
    sharpe_diff = r['sharpe_net'] - r_old['sharpe_net']
    print(f"    {r['name'][:45]:<45}: Sharpe diff={sharpe_diff:+.3f}, DM t={dm_t:.3f}, p={dm_p:.4f}")

# ============================================================
# 14. Transaction Cost Sensitivity
# ============================================================
print("\n\n[12] Transaction Cost Sensitivity for Best Strategy")
print("=" * 70)

tx_costs = [0.001, 0.002, 0.003, 0.004, 0.00585, 0.008, 0.01, 0.015, 0.02]
tx_sens_results = []

for tx in tx_costs:
    sig = signal_funcs[best_key](mdf)
    res = backtest_monthly(sig, mdf['tw_ret'], best_key, tx_cost=tx)
    tx_sens_results.append({
        'tx_cost_pct': round(tx * 100, 2),
        'sharpe_net': res['sharpe_net'],
        'ann_return_net_pct': res['ann_return_net_pct'],
        'mdd_net_pct': res['mdd_net_pct'],
    })
    print(f"  TX={tx*100:.2f}%: Sharpe={res['sharpe_net']:.3f}, Return={res['ann_return_net_pct']:.2f}%, MDD={res['mdd_net_pct']:.2f}%")

# ============================================================
# 15. Upside/Downside Capture Analysis
# ============================================================
print("\n\n[13] Upside/Downside Capture Analysis")
print("=" * 70)

for key in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    r = results[key]
    strat_ret = r['strat_ret_net']
    bh = bh_monthly_ret

    common = strat_ret.index.intersection(bh.index)
    s = strat_ret.loc[common]
    b = bh.loc[common]

    up_months = b > 0
    dn_months = b < 0

    if up_months.sum() > 0:
        upside_capture = float(s[up_months].mean() / b[up_months].mean() * 100)
    else:
        upside_capture = 0
    if dn_months.sum() > 0:
        downside_capture = float(s[dn_months].mean() / b[dn_months].mean() * 100)
    else:
        downside_capture = 0

    capture_ratio = upside_capture / downside_capture if downside_capture != 0 else 0

    print(f"  {r['name'][:40]:<40}: Up={upside_capture:.1f}%, Dn={downside_capture:.1f}%, Ratio={capture_ratio:.2f}")

# ============================================================
# 16. Assessment & Conclusion
# ============================================================
print("\n\n[14] Assessment & Listing Decision")
print("=" * 70)

# Check listing criteria
best_r = results[best_key]
vt_r = results['vt_863']

criteria = {
    'net_sharpe_gt_vt': best_r['sharpe_net'] > vt_r['sharpe_net'],
    'net_sharpe_value': best_r['sharpe_net'],
    'vt_sharpe_value': vt_r['sharpe_net'],

    'cross_oos_positive': sum(1 for r in oos_results[best_key] if r['sharpe_net'] > 0),
    'cross_oos_total': len(oos_results[best_key]),
    'cross_oos_pass': sum(1 for r in oos_results[best_key] if r['sharpe_net'] > 0) >= 4,

    'harvey_t': best_r['t_stat_net'],
    'harvey_pass': abs(best_r['t_stat_net']) > 3.0,
}

print(f"\n  Best strategy: {best_r['name']}")
print(f"  Net Sharpe: {best_r['sharpe_net']:.3f} vs 8.63/VIX: {vt_r['sharpe_net']:.3f}")
print(f"  Criterion 1 (Sharpe > VT): {'PASS' if criteria['net_sharpe_gt_vt'] else 'FAIL'}")
print(f"  Cross-OOS positive: {criteria['cross_oos_positive']}/{criteria['cross_oos_total']}")
print(f"  Criterion 2 (Cross-OOS ≥ 4/5): {'PASS' if criteria['cross_oos_pass'] else 'FAIL'}")
print(f"  Harvey t-stat: {criteria['harvey_t']:.3f}")
print(f"  Criterion 3 (Harvey t > 3.0): {'PASS' if criteria['harvey_pass'] else 'FAIL'}")

all_pass = criteria['net_sharpe_gt_vt'] and criteria['cross_oos_pass'] and criteria['harvey_pass']
print(f"\n  LISTING DECISION: {'RECOMMEND (all criteria pass)' if all_pass else 'DO NOT LIST (criteria not met)'}")

if not all_pass:
    failures = []
    if not criteria['net_sharpe_gt_vt']:
        failures.append(f"Sharpe {best_r['sharpe_net']:.3f} ≤ VT {vt_r['sharpe_net']:.3f}")
    if not criteria['cross_oos_pass']:
        failures.append(f"Cross-OOS {criteria['cross_oos_positive']}/{criteria['cross_oos_total']} < 4/5")
    if not criteria['harvey_pass']:
        failures.append(f"Harvey t={criteria['harvey_t']:.3f} < 3.0")
    print(f"  Reasons: {'; '.join(failures)}")

# ============================================================
# 17. Save Results
# ============================================================
elapsed = time.time() - start_time
print(f"\n\nExecution time: {elapsed:.1f} seconds")

# Clean results for JSON serialization (remove pandas objects)
def clean_for_json(d):
    """Remove non-serializable objects from results dict."""
    cleaned = {}
    for k, v in d.items():
        if isinstance(v, (pd.Series, pd.DataFrame)):
            continue  # skip pandas objects
        elif isinstance(v, dict):
            cleaned[k] = clean_for_json(v)
        elif isinstance(v, (np.integer,)):
            cleaned[k] = int(v)
        elif isinstance(v, (np.floating,)):
            cleaned[k] = float(v)
        elif isinstance(v, np.ndarray):
            cleaned[k] = v.tolist()
        else:
            cleaned[k] = v
    return cleaned

# Build OOS summary for JSON
oos_summary = {}
for strat_name in ['spy_signal', 'vix_signal', 'spy_vix_signal', 'spy_vix_vt', 'vt_863']:
    if strat_name not in oos_results:
        continue
    oos_summary[strat_name] = []
    for r in oos_results[strat_name]:
        oos_summary[strat_name].append({
            'period': r.get('oos_period', ''),
            'n_months': r.get('oos_n_months', r.get('n_months', 0)),
            'sharpe_net': r['sharpe_net'],
            'ann_return_net_pct': r['ann_return_net_pct'],
            'mdd_net_pct': r['mdd_net_pct'],
        })

output = {
    'experiment_id': 'K517',
    'title': 'Monthly Overnight Gap Strategy — General Investor Version',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'attribution': '[提出: 用戶, 執行: Claude]',
    'data_source': 'yfinance: 0050.TW, SPY, ^VIX',
    'data_period': f"{mdf.index[0].strftime('%Y-%m')} to {mdf.index[-1].strftime('%Y-%m')}",
    'n_months': len(mdf),
    'tx_cost_pct': 0.585,
    'tx_cost_description': '0.585% round-trip ETF (bid-ask + commission)',
    'references': [
        'K515: Taiwan Overnight Gap — alpha real but ETF TX fatal',
        'K516: Futures 5bp TX Sharpe 0.93, 5/5 cross-OOS',
        'K502: 77-93% alpha in overnight gap',
        'Lou, Polk, Skouras (2019): A Tug of War: Overnight vs Intraday Returns, JFE',
        '8.63/VIX Taiwan VT: existing strategy benchmark',
    ],
    'diagnostics': {
        'tw_monthly_ret_mean_pct': round(mdf['tw_ret'].mean() * 100, 3),
        'tw_monthly_ret_std_pct': round(mdf['tw_ret'].std() * 100, 3),
        'tw_monthly_ret_skew': round(float(mdf['tw_ret'].skew()), 3),
        'tw_monthly_ret_kurt': round(float(mdf['tw_ret'].kurtosis()), 3),
        'spy_monthly_ret_mean_pct': round(mdf['spy_ret'].mean() * 100, 3),
        'vix_mean': round(float(mdf['vix'].mean()), 1),
        'corr_tw_vs_prior_spy': round(corr_tw_spy, 4),
        'corr_tw_vs_prior_vix': round(corr_tw_vix, 4),
        'spy_up_tw_ret_pct': round(float(spy_up.mean() * 100), 2),
        'spy_dn_tw_ret_pct': round(float(spy_dn.mean() * 100), 2),
        'spy_conditioning_t': round(float(t_spy), 3),
        'spy_conditioning_p': round(float(p_spy), 4),
        'vix_low_tw_ret_pct': round(float(vix_low.mean() * 100), 2),
        'vix_high_tw_ret_pct': round(float(vix_high.mean() * 100), 2),
        'vix_conditioning_t': round(float(t_vix), 3),
        'vix_conditioning_p': round(float(p_vix), 4),
    },
    'strategies': {k: clean_for_json(v) for k, v in results.items()},
    'benchmarks': {
        'buy_and_hold': bh_result,
    },
    'cross_oos': {
        'periods': [f"{s} to {e}" for s, e in oos_periods],
        'results': oos_summary,
    },
    'dm_tests_vs_bh': dm_results,
    'vix_threshold_sensitivity': sensitivity_results,
    'spy_threshold_sensitivity': spy_sens,
    'tx_cost_sensitivity': tx_sens_results,
    'yearly_breakdown': yearly_data,
    'listing_criteria': criteria,
    'listing_decision': 'RECOMMEND' if all_pass else 'DO NOT LIST',
    'conclusion': '',  # Will be filled below
    'execution_time_seconds': round(elapsed, 1),
}

# Generate conclusion
if all_pass:
    output['conclusion'] = (
        f"Monthly SPY+VIX timing strategy ({best_r['name']}) PASSES all listing criteria: "
        f"Net Sharpe {best_r['sharpe_net']:.3f} > VT {vt_r['sharpe_net']:.3f}, "
        f"Cross-OOS {criteria['cross_oos_positive']}/{criteria['cross_oos_total']}, "
        f"Harvey t={criteria['harvey_t']:.3f}. "
        f"Suitable for general investors with 0.585% RT TX cost."
    )
else:
    output['conclusion'] = (
        f"Monthly SPY signal strategies DO NOT meet listing criteria. "
        f"Best strategy ({best_r['name']}): Net Sharpe={best_r['sharpe_net']:.3f} "
        f"(vs VT {vt_r['sharpe_net']:.3f}), "
        f"Cross-OOS {criteria['cross_oos_positive']}/{criteria['cross_oos_total']}, "
        f"Harvey t={criteria['harvey_t']:.3f}. "
        f"Monthly SPY conditioning is not a significant improvement over simple 8.63/VIX VT. "
        f"The overnight gap alpha (K515/K516) does not translate to monthly timing improvement "
        f"because: (1) monthly aggregation dilutes the daily signal, "
        f"(2) SPY→Taiwan lead-lag is mostly in overnight gap (K502: 77-93%), "
        f"(3) simple VIX-based VT already captures the relevant risk-off signal."
    )

# Save
output_path = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a820c0e7/experiments/k517_monthly_overnight_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print(f"\nConclusion: {output['conclusion']}")
print("\nDone.")
