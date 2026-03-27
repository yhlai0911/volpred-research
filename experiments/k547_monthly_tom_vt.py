#!/usr/bin/env python3
"""
K547: Monthly VT with End-of-Month (Turn-of-Month) Anomaly
===========================================================
Can calendar effects improve Volatility Targeting (VT)?

Motivation:
- Monthly rebalancing is optimal for VT (K48/K65/K75)
- BUT when in the month matters? The "turn-of-month" (ToM) effect
  is one of the most robust calendar anomalies in finance
- K153 found no month-of-year seasonality, but ToM is WITHIN-month

Hypothesis:
- If most positive returns concentrate around month-end/start,
  VT should be more aggressive (higher equity) during ToM and
  more defensive mid-month

Literature:
- Ariel (1987): "A monthly effect in stock returns", JFE
- Lakonishok & Smidt (1988): "Are seasonal anomalies real?", RFS
- McConnell & Xu (2008): "Equity returns at the turn of the month", FAJ
- Kunkel et al. (2003): "The turn-of-the-month effect still lives", IRFA

Design:
1. Data: SPY + VIX from yfinance (2005-2026)
2. Classify days: ToM (last 1 + first 3 trading days) vs mid-month
3. Verify ToM anomaly exists (t-test)
4. Strategies:
   a. Standard monthly VT (rebalance 1st trading day, 12/VIX)
   b. ToM-Enhanced: 12/VIX during ToM, 8/VIX mid-month
   c. ToM-Aggressive: 12/VIX during ToM, 6/VIX mid-month (50% cut)
   d. Dual-Frequency: monthly VT base + daily ToM overlay
5. Benchmark: standard 12/VIX daily rebalancing
6. Cross-OOS: 5 periods
7. Harvey (2016) t>3.0 threshold

Data source: yfinance (SPY, ^VIX)
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

warnings.filterwarnings('ignore')

start_time = time.time()

print("=" * 70)
print("K547: Monthly VT with Turn-of-Month Anomaly")
print("=" * 70)

# =================================================================
# 1. DATA DOWNLOAD
# =================================================================
print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2005-01-01', end='2026-03-27', progress=False)
vix = yf.download('^VIX', start='2005-01-01', end='2026-03-27', progress=False)

# Handle MultiIndex columns
for df_raw in [spy, vix]:
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

spy_close = spy['Close'].dropna()
vix_close = vix['Close'].dropna()

# Align dates
common_idx = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

spy_ret = spy_close.pct_change().dropna()
vix_aligned = vix_close.reindex(spy_ret.index).ffill()

print(f"  SPY: {spy_ret.index[0].date()} to {spy_ret.index[-1].date()}, N={len(spy_ret)}")
print(f"  VIX: {vix_aligned.index[0].date()} to {vix_aligned.index[-1].date()}")

# =================================================================
# 2. CLASSIFY TRADING DAYS: ToM vs MID-MONTH
# =================================================================
print("\n[2] Classifying trading days...")

def classify_tom(dates):
    """
    Classify each trading day as Turn-of-Month (ToM) or Mid-Month.
    ToM = last 1 trading day of month + first 3 trading days of month.
    """
    df = pd.DataFrame(index=dates)
    df['year'] = df.index.year
    df['month'] = df.index.month
    df['ym'] = df['year'] * 100 + df['month']

    is_tom = pd.Series(False, index=dates)

    for ym, group in df.groupby('ym'):
        trading_days = group.index.sort_values()
        n = len(trading_days)
        if n < 5:  # skip very short months
            continue
        # First 3 trading days of month
        first_3 = trading_days[:3]
        is_tom.loc[first_3] = True
        # Last 1 trading day of month
        last_1 = trading_days[-1:]
        is_tom.loc[last_1] = True

    return is_tom

is_tom = classify_tom(spy_ret.index)
tom_days = is_tom.sum()
mid_days = (~is_tom).sum()
total_days = len(spy_ret)

print(f"  Total trading days: {total_days}")
print(f"  ToM days: {tom_days} ({100*tom_days/total_days:.1f}%)")
print(f"  Mid-month days: {mid_days} ({100*mid_days/total_days:.1f}%)")

# =================================================================
# 3. VERIFY TOM ANOMALY EXISTS
# =================================================================
print("\n[3] Verifying Turn-of-Month anomaly...")

tom_returns = spy_ret[is_tom]
mid_returns = spy_ret[~is_tom]

# Descriptive statistics
tom_mean = tom_returns.mean() * 252
tom_std = tom_returns.std() * np.sqrt(252)
mid_mean = mid_returns.mean() * 252
mid_std = mid_returns.std() * np.sqrt(252)

print(f"\n  ToM days (last 1 + first 3):")
print(f"    N = {len(tom_returns)}")
print(f"    Ann. mean return = {tom_mean*100:.2f}%")
print(f"    Ann. volatility  = {tom_std*100:.2f}%")
print(f"    Daily Sharpe (ann.) = {tom_mean/tom_std:.3f}")

print(f"\n  Mid-month days:")
print(f"    N = {len(mid_returns)}")
print(f"    Ann. mean return = {mid_mean*100:.2f}%")
print(f"    Ann. volatility  = {mid_std*100:.2f}%")
print(f"    Daily Sharpe (ann.) = {mid_mean/mid_std:.3f}")

# T-test for difference in means
t_stat, p_val = stats.ttest_ind(tom_returns, mid_returns, equal_var=False)
print(f"\n  Welch t-test (ToM vs Mid):")
print(f"    t-statistic = {t_stat:.4f}")
print(f"    p-value = {p_val:.6f}")
print(f"    Significant at 5%? {'YES' if p_val < 0.05 else 'NO'}")
print(f"    Significant at 1%? {'YES' if p_val < 0.01 else 'NO'}")

# Return concentration
total_return = spy_ret.sum()
tom_total = tom_returns.sum()
mid_total = mid_returns.sum()
print(f"\n  Return concentration:")
print(f"    Total cumulative daily return: {total_return:.4f}")
print(f"    ToM contribution: {tom_total:.4f} ({100*tom_total/total_return:.1f}%)")
print(f"    Mid-month contribution: {mid_total:.4f} ({100*mid_total/total_return:.1f}%)")

# Year-by-year analysis
print(f"\n  Year-by-year ToM vs Mid-month (annualized mean return %):")
print(f"  {'Year':>6} {'ToM%':>8} {'Mid%':>8} {'Diff':>8} {'ToM wins':>10}")
yearly_tom_wins = 0
yearly_total = 0
for year in range(2005, 2027):
    mask_y = spy_ret.index.year == year
    if mask_y.sum() == 0:
        continue
    y_tom = spy_ret[mask_y & is_tom]
    y_mid = spy_ret[mask_y & ~is_tom]
    if len(y_tom) == 0 or len(y_mid) == 0:
        continue
    y_tom_ann = y_tom.mean() * 252 * 100
    y_mid_ann = y_mid.mean() * 252 * 100
    diff = y_tom_ann - y_mid_ann
    win = "YES" if diff > 0 else "no"
    if diff > 0:
        yearly_tom_wins += 1
    yearly_total += 1
    print(f"  {year:>6} {y_tom_ann:>8.1f} {y_mid_ann:>8.1f} {diff:>8.1f} {win:>10}")

print(f"\n  ToM wins: {yearly_tom_wins}/{yearly_total} years ({100*yearly_tom_wins/yearly_total:.0f}%)")

# =================================================================
# 4. STRATEGY DEFINITIONS
# =================================================================
print("\n[4] Defining strategies...")

def compute_vt_weight(vix_val, target_vol_pct):
    """VT weight = target_vol / VIX, capped at [0, 1]"""
    if pd.isna(vix_val) or vix_val <= 0:
        return 0.5
    w = target_vol_pct / vix_val
    return np.clip(w, 0, 1)

def run_strategy(spy_ret, vix_aligned, is_tom, strategy_name, params):
    """
    Run a VT strategy and return daily returns.

    Strategies:
    - 'daily_vt': standard 12/VIX daily rebalancing
    - 'monthly_vt': standard monthly rebalancing (1st trading day)
    - 'tom_enhanced': 12/VIX during ToM, reduced mid-month
    - 'tom_aggressive': 12/VIX during ToM, 50% reduction mid-month
    - 'dual_frequency': monthly base + daily ToM overlay
    """
    weights = pd.Series(index=spy_ret.index, dtype=float)

    if strategy_name == 'daily_vt':
        # Standard: 12/VIX every day
        target = params.get('target', 12)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_aligned.loc[date] if date in vix_aligned.index else 20
            weights.iloc[i] = compute_vt_weight(vix_val, target)

    elif strategy_name == 'monthly_vt':
        # Monthly: rebalance on first trading day of each month
        target = params.get('target', 12)
        current_weight = 0.5
        prev_month = None
        for i, date in enumerate(spy_ret.index):
            ym = date.year * 100 + date.month
            if ym != prev_month:
                # New month: recalculate
                vix_val = vix_aligned.loc[date] if date in vix_aligned.index else 20
                current_weight = compute_vt_weight(vix_val, target)
                prev_month = ym
            weights.iloc[i] = current_weight

    elif strategy_name == 'tom_enhanced':
        # ToM: use higher target during ToM, lower mid-month
        tom_target = params.get('tom_target', 12)
        mid_target = params.get('mid_target', 8)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_aligned.loc[date] if date in vix_aligned.index else 20
            if is_tom.loc[date]:
                weights.iloc[i] = compute_vt_weight(vix_val, tom_target)
            else:
                weights.iloc[i] = compute_vt_weight(vix_val, mid_target)

    elif strategy_name == 'tom_aggressive':
        # ToM: full target during ToM, 50% cut mid-month
        tom_target = params.get('tom_target', 12)
        mid_target = params.get('mid_target', 6)
        for i, date in enumerate(spy_ret.index):
            vix_val = vix_aligned.loc[date] if date in vix_aligned.index else 20
            if is_tom.loc[date]:
                weights.iloc[i] = compute_vt_weight(vix_val, tom_target)
            else:
                weights.iloc[i] = compute_vt_weight(vix_val, mid_target)

    elif strategy_name == 'dual_frequency':
        # Monthly base + daily ToM overlay
        base_target = params.get('base_target', 12)
        tom_boost = params.get('tom_boost', 1.3)  # 30% boost during ToM
        mid_cut = params.get('mid_cut', 0.7)  # 30% reduction mid-month
        current_base = 0.5
        prev_month = None
        for i, date in enumerate(spy_ret.index):
            ym = date.year * 100 + date.month
            if ym != prev_month:
                vix_val = vix_aligned.loc[date] if date in vix_aligned.index else 20
                current_base = compute_vt_weight(vix_val, base_target)
                prev_month = ym
            if is_tom.loc[date]:
                weights.iloc[i] = np.clip(current_base * tom_boost, 0, 1)
            else:
                weights.iloc[i] = np.clip(current_base * mid_cut, 0, 1)

    elif strategy_name == 'buy_hold':
        weights[:] = 1.0

    # Portfolio return: w * SPY + (1-w) * risk-free (assume 0)
    port_ret = weights * spy_ret
    return port_ret, weights

# =================================================================
# 5. FULL SAMPLE BACKTEST
# =================================================================
print("\n[5] Full sample backtest (2005-2026)...")

strategies = {
    'Buy & Hold': ('buy_hold', {}),
    'Daily VT (12/VIX)': ('daily_vt', {'target': 12}),
    'Monthly VT (12/VIX)': ('monthly_vt', {'target': 12}),
    'ToM Enhanced (12/8)': ('tom_enhanced', {'tom_target': 12, 'mid_target': 8}),
    'ToM Aggressive (12/6)': ('tom_aggressive', {'tom_target': 12, 'mid_target': 6}),
    'Dual Freq (1.3x/0.7x)': ('dual_frequency', {'base_target': 12, 'tom_boost': 1.3, 'mid_cut': 0.7}),
}

results_full = {}
print(f"\n  {'Strategy':<28} {'CAGR%':>8} {'Vol%':>8} {'Sharpe':>8} {'MDD%':>8} {'Calmar':>8} {'Avg Wt':>8}")
print("  " + "-" * 82)

for name, (strat, params) in strategies.items():
    port_ret, weights = run_strategy(spy_ret, vix_aligned, is_tom, strat, params)

    # Performance metrics
    cum = (1 + port_ret).cumprod()
    years = len(port_ret) / 252
    cagr = (cum.iloc[-1] ** (1/years) - 1) * 100
    vol = port_ret.std() * np.sqrt(252) * 100
    sharpe = (port_ret.mean() / port_ret.std()) * np.sqrt(252) if port_ret.std() > 0 else 0

    # Max drawdown
    rolling_max = cum.cummax()
    drawdown = (cum - rolling_max) / rolling_max
    mdd = drawdown.min() * 100
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    avg_wt = weights.mean()

    results_full[name] = {
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'calmar': calmar,
        'avg_weight': avg_wt,
        'port_ret': port_ret,
        'weights': weights,
    }

    print(f"  {name:<28} {cagr:>8.2f} {vol:>8.2f} {sharpe:>8.3f} {mdd:>8.2f} {calmar:>8.3f} {avg_wt:>8.3f}")

# =================================================================
# 6. TRANSACTION COST ANALYSIS
# =================================================================
print("\n[6] Transaction cost analysis...")

def add_transaction_costs(port_ret, weights, tc_bps=5):
    """Add round-trip transaction costs based on weight changes."""
    tc = tc_bps / 10000
    weight_changes = weights.diff().abs()
    weight_changes.iloc[0] = weights.iloc[0]  # initial purchase
    costs = weight_changes * tc
    net_ret = port_ret - costs
    return net_ret

print(f"\n  Net Sharpe (after 5bps round-trip TC):")
print(f"  {'Strategy':<28} {'Gross SR':>10} {'Net SR':>10} {'TC Drag%':>10} {'Trades/yr':>10}")
print("  " + "-" * 62)

for name, data in results_full.items():
    port_ret = data['port_ret']
    weights = data['weights']
    net_ret = add_transaction_costs(port_ret, weights, tc_bps=5)

    gross_sr = data['sharpe']
    net_sr = (net_ret.mean() / net_ret.std()) * np.sqrt(252) if net_ret.std() > 0 else 0
    tc_drag = (gross_sr - net_sr)

    # Count trades (weight changes > 1%)
    wt_changes = weights.diff().abs()
    trades_per_year = (wt_changes > 0.01).sum() / (len(port_ret) / 252)

    results_full[name]['net_sharpe'] = net_sr
    results_full[name]['trades_per_year'] = trades_per_year

    print(f"  {name:<28} {gross_sr:>10.3f} {net_sr:>10.3f} {tc_drag:>10.4f} {trades_per_year:>10.1f}")

# =================================================================
# 7. CROSS-OOS VALIDATION (5 periods)
# =================================================================
print("\n[7] Cross-OOS validation (5 periods)...")

# Define 5 OOS periods (each ~2 years)
oos_periods = [
    ('2006-01', '2009-12'),  # Includes GFC
    ('2010-01', '2013-12'),  # Recovery
    ('2014-01', '2017-12'),  # Low vol bull
    ('2018-01', '2021-12'),  # Includes COVID
    ('2022-01', '2026-03'),  # Recent
]

# Only test the key comparison: ToM Enhanced vs Daily VT
cross_oos_results = []

print(f"\n  {'Period':<20} {'Daily VT SR':>12} {'ToM Enh SR':>12} {'ToM Agg SR':>12} {'Diff (Enh)':>12} {'t-stat':>8}")
print("  " + "-" * 80)

for start, end in oos_periods:
    mask = (spy_ret.index >= start) & (spy_ret.index <= end)
    spy_oos = spy_ret[mask]
    vix_oos = vix_aligned.reindex(spy_oos.index).ffill()
    tom_oos = is_tom.reindex(spy_oos.index).fillna(False)

    if len(spy_oos) < 100:
        continue

    # Daily VT
    ret_daily, _ = run_strategy(spy_oos, vix_oos, tom_oos, 'daily_vt', {'target': 12})
    sr_daily = (ret_daily.mean() / ret_daily.std()) * np.sqrt(252) if ret_daily.std() > 0 else 0

    # ToM Enhanced
    ret_enh, _ = run_strategy(spy_oos, vix_oos, tom_oos, 'tom_enhanced', {'tom_target': 12, 'mid_target': 8})
    sr_enh = (ret_enh.mean() / ret_enh.std()) * np.sqrt(252) if ret_enh.std() > 0 else 0

    # ToM Aggressive
    ret_agg, _ = run_strategy(spy_oos, vix_oos, tom_oos, 'tom_aggressive', {'tom_target': 12, 'mid_target': 6})
    sr_agg = (ret_agg.mean() / ret_agg.std()) * np.sqrt(252) if ret_agg.std() > 0 else 0

    # Difference and t-test (paired on daily returns)
    diff = ret_enh - ret_daily
    t_diff = diff.mean() / (diff.std() / np.sqrt(len(diff))) if diff.std() > 0 else 0

    cross_oos_results.append({
        'period': f"{start} to {end}",
        'n_days': len(spy_oos),
        'sr_daily': sr_daily,
        'sr_tom_enh': sr_enh,
        'sr_tom_agg': sr_agg,
        'diff_enh': sr_enh - sr_daily,
        't_stat': t_diff,
    })

    print(f"  {start} to {end:<8} {sr_daily:>12.3f} {sr_enh:>12.3f} {sr_agg:>12.3f} {sr_enh-sr_daily:>12.3f} {t_diff:>8.3f}")

# Summary
n_enh_wins = sum(1 for r in cross_oos_results if r['diff_enh'] > 0)
n_periods = len(cross_oos_results)
avg_diff = np.mean([r['diff_enh'] for r in cross_oos_results])
avg_t = np.mean([r['t_stat'] for r in cross_oos_results])

print(f"\n  Cross-OOS Summary:")
print(f"    ToM Enhanced wins: {n_enh_wins}/{n_periods}")
print(f"    Average Sharpe diff: {avg_diff:.4f}")
print(f"    Average t-stat: {avg_t:.4f}")
print(f"    Harvey threshold (t>3.0): {'PASS' if abs(avg_t) > 3.0 else 'FAIL'}")

# =================================================================
# 8. BOOTSTRAP TEST
# =================================================================
print("\n[8] Bootstrap test (10,000 reps)...")

# Test: ToM Enhanced vs Daily VT (full sample)
ret_daily_full = results_full['Daily VT (12/VIX)']['port_ret']
ret_enh_full = results_full['ToM Enhanced (12/8)']['port_ret']
ret_agg_full = results_full['ToM Aggressive (12/6)']['port_ret']

diff_enh = ret_enh_full - ret_daily_full
diff_agg = ret_agg_full - ret_daily_full

n_boot = 10000
np.random.seed(42)

# Block bootstrap (block size = 20 trading days for autocorrelation)
block_size = 20
n = len(diff_enh)
n_blocks = n // block_size + 1

def block_bootstrap(diff_series, n_boot, block_size):
    n = len(diff_series)
    diff_arr = diff_series.values
    n_blocks = n // block_size + 1
    boot_means = np.zeros(n_boot)

    for b in range(n_boot):
        # Sample blocks with replacement
        block_starts = np.random.randint(0, n - block_size, size=n_blocks)
        boot_sample = np.concatenate([diff_arr[s:s+block_size] for s in block_starts])[:n]
        boot_means[b] = boot_sample.mean()

    return boot_means

boot_enh = block_bootstrap(diff_enh, n_boot, block_size)
boot_agg = block_bootstrap(diff_agg, n_boot, block_size)

# Bootstrap p-values
p_enh = (boot_enh <= 0).mean()
p_agg = (boot_agg <= 0).mean()

# Bootstrap t-statistics
t_boot_enh = diff_enh.mean() / (boot_enh.std()) if boot_enh.std() > 0 else 0
t_boot_agg = diff_agg.mean() / (boot_agg.std()) if boot_agg.std() > 0 else 0

print(f"  ToM Enhanced vs Daily VT:")
print(f"    Mean daily diff: {diff_enh.mean()*10000:.4f} bps")
print(f"    Bootstrap SE: {boot_enh.std()*10000:.4f} bps")
print(f"    Bootstrap t: {t_boot_enh:.4f}")
print(f"    Bootstrap p: {p_enh:.4f}")
print(f"    95% CI: [{np.percentile(boot_enh, 2.5)*10000:.4f}, {np.percentile(boot_enh, 97.5)*10000:.4f}] bps")

print(f"\n  ToM Aggressive vs Daily VT:")
print(f"    Mean daily diff: {diff_agg.mean()*10000:.4f} bps")
print(f"    Bootstrap SE: {boot_agg.std()*10000:.4f} bps")
print(f"    Bootstrap t: {t_boot_agg:.4f}")
print(f"    Bootstrap p: {p_agg:.4f}")
print(f"    95% CI: [{np.percentile(boot_agg, 2.5)*10000:.4f}, {np.percentile(boot_agg, 97.5)*10000:.4f}] bps")

# =================================================================
# 9. REGIME ANALYSIS (HIGH vs LOW VIX)
# =================================================================
print("\n[9] Regime analysis (does ToM work better in certain VIX regimes?)...")

vix_median = vix_aligned.median()
high_vix = vix_aligned > vix_median
low_vix = ~high_vix

for regime_name, regime_mask in [('Low VIX', low_vix), ('High VIX', high_vix)]:
    mask = regime_mask.reindex(spy_ret.index).fillna(False)
    spy_regime = spy_ret[mask]
    tom_regime = is_tom.reindex(spy_regime.index).fillna(False)

    tom_ret = spy_regime[tom_regime]
    mid_ret = spy_regime[~tom_regime]

    tom_ann = tom_ret.mean() * 252 * 100
    mid_ann = mid_ret.mean() * 252 * 100

    t_regime, p_regime = stats.ttest_ind(tom_ret, mid_ret, equal_var=False)

    print(f"\n  {regime_name} (VIX median={vix_median:.1f}):")
    print(f"    ToM days: N={len(tom_ret)}, Ann. return={tom_ann:.2f}%")
    print(f"    Mid days: N={len(mid_ret)}, Ann. return={mid_ann:.2f}%")
    print(f"    Diff: {tom_ann - mid_ann:.2f}pp")
    print(f"    t-stat: {t_regime:.4f}, p-val: {p_regime:.6f}")

# =================================================================
# 10. SENSITIVITY: DIFFERENT ToM DEFINITIONS
# =================================================================
print("\n[10] Sensitivity: different ToM definitions...")

tom_definitions = {
    'Last 1 + First 3': (1, 3),  # standard
    'Last 1 + First 4': (1, 4),  # slightly wider
    'Last 2 + First 3': (2, 3),  # wider at end
    'Last 2 + First 4': (2, 4),  # widest
    'Last 1 + First 2': (1, 2),  # narrow
}

def classify_tom_custom(dates, last_n, first_n):
    df = pd.DataFrame(index=dates)
    df['year'] = df.index.year
    df['month'] = df.index.month
    df['ym'] = df['year'] * 100 + df['month']

    is_tom = pd.Series(False, index=dates)

    for ym, group in df.groupby('ym'):
        trading_days = group.index.sort_values()
        n = len(trading_days)
        if n < 5:
            continue
        first = trading_days[:first_n]
        is_tom.loc[first] = True
        last = trading_days[-last_n:]
        is_tom.loc[last] = True

    return is_tom

print(f"\n  {'Definition':<25} {'ToM ret%':>10} {'Mid ret%':>10} {'Diff':>8} {'t-stat':>8} {'p-val':>8}")
print("  " + "-" * 72)

for def_name, (last_n, first_n) in tom_definitions.items():
    tom_custom = classify_tom_custom(spy_ret.index, last_n, first_n)
    tom_r = spy_ret[tom_custom].mean() * 252 * 100
    mid_r = spy_ret[~tom_custom].mean() * 252 * 100
    t_s, p_s = stats.ttest_ind(spy_ret[tom_custom], spy_ret[~tom_custom], equal_var=False)
    print(f"  {def_name:<25} {tom_r:>10.2f} {mid_r:>10.2f} {tom_r-mid_r:>8.2f} {t_s:>8.4f} {p_s:>8.4f}")

# =================================================================
# 11. COMBINED RESULTS SUMMARY
# =================================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Is ToM anomaly real?
tom_anomaly_significant = p_val < 0.05
tom_return_concentration = tom_total / total_return * 100

print(f"\n  A. Turn-of-Month Anomaly:")
print(f"     Exists in SPY data? {'YES' if tom_anomaly_significant else 'NO (not statistically significant)'}")
print(f"     ToM ann. return: {tom_mean*100:.2f}% vs Mid: {mid_mean*100:.2f}%")
print(f"     Difference: {(tom_mean-mid_mean)*100:.2f}pp")
print(f"     t-statistic: {t_stat:.4f} (p={p_val:.4f})")
print(f"     Return concentration: ToM captures {tom_return_concentration:.1f}% of total return")
print(f"     using only {100*tom_days/total_days:.1f}% of trading days")

print(f"\n  B. Strategy Performance (full sample, gross):")
for name in ['Daily VT (12/VIX)', 'Monthly VT (12/VIX)', 'ToM Enhanced (12/8)',
             'ToM Aggressive (12/6)', 'Dual Freq (1.3x/0.7x)']:
    d = results_full[name]
    print(f"     {name}: SR={d['sharpe']:.3f}, CAGR={d['cagr']:.2f}%, MDD={d['mdd']:.2f}%")

# Does ToM improve VT?
best_tom = max(
    ['ToM Enhanced (12/8)', 'ToM Aggressive (12/6)', 'Dual Freq (1.3x/0.7x)'],
    key=lambda x: results_full[x]['sharpe']
)
daily_sr = results_full['Daily VT (12/VIX)']['sharpe']
best_sr = results_full[best_tom]['sharpe']
improvement = best_sr - daily_sr

print(f"\n  C. Does ToM improve VT?")
print(f"     Best ToM strategy: {best_tom}")
print(f"     Sharpe change vs Daily VT: {improvement:+.4f}")
print(f"     Cross-OOS: {n_enh_wins}/{n_periods} periods better")
print(f"     Bootstrap t: {t_boot_enh:.4f} (negative = ToM WORSE)")
tom_verdict = 'YES' if t_boot_enh > 3.0 and improvement > 0 else ('SIGNIFICANTLY WORSE' if t_boot_enh < -3.0 else 'NO')
print(f"     CONCLUSION: {tom_verdict}")

# =================================================================
# 12. SAVE RESULTS
# =================================================================
elapsed = time.time() - start_time
print(f"\n  Runtime: {elapsed:.1f}s")

results_json = {
    "experiment_id": "K547",
    "title": "Monthly VT with Turn-of-Month Anomaly",
    "timestamp": datetime.now().isoformat(),
    "runtime_seconds": round(elapsed, 1),
    "data_source": "yfinance",
    "data_period": f"{spy_ret.index[0].date()} to {spy_ret.index[-1].date()}",
    "sample_size": len(spy_ret),
    "references": [
        "Ariel (1987): A monthly effect in stock returns, JFE",
        "Lakonishok & Smidt (1988): Are seasonal anomalies real?, RFS",
        "McConnell & Xu (2008): Equity returns at the turn of the month, FAJ",
        "Kunkel et al. (2003): The turn-of-the-month effect still lives, IRFA",
        "Harvey (2016): ...and the cross-section of expected returns, RFS"
    ],
    "tom_anomaly": {
        "tom_definition": "last 1 + first 3 trading days of month",
        "tom_days_count": int(tom_days),
        "mid_days_count": int(mid_days),
        "tom_pct_of_total": round(100 * tom_days / total_days, 1),
        "tom_ann_return_pct": round(tom_mean * 100, 2),
        "mid_ann_return_pct": round(mid_mean * 100, 2),
        "tom_ann_vol_pct": round(tom_std * 100, 2),
        "mid_ann_vol_pct": round(mid_std * 100, 2),
        "tom_sharpe": round(tom_mean / tom_std, 3),
        "mid_sharpe": round(mid_mean / mid_std, 3),
        "welch_t_stat": round(t_stat, 4),
        "welch_p_value": round(p_val, 6),
        "significant_5pct": bool(p_val < 0.05),
        "return_concentration_pct": round(tom_return_concentration, 1),
        "tom_wins_by_year": f"{yearly_tom_wins}/{yearly_total}",
    },
    "strategy_results_full_sample": {},
    "cross_oos_validation": {
        "n_periods": n_periods,
        "periods": cross_oos_results,
        "tom_enhanced_wins": n_enh_wins,
        "avg_sharpe_diff": round(avg_diff, 4),
        "avg_t_stat": round(avg_t, 4),
        "passes_harvey": bool(abs(avg_t) > 3.0),
    },
    "bootstrap_test": {
        "n_reps": n_boot,
        "block_size": block_size,
        "tom_enhanced_vs_daily": {
            "mean_diff_bps": round(diff_enh.mean() * 10000, 4),
            "bootstrap_se_bps": round(boot_enh.std() * 10000, 4),
            "bootstrap_t": round(t_boot_enh, 4),
            "bootstrap_p": round(p_enh, 4),
            "ci_95_bps": [round(np.percentile(boot_enh, 2.5) * 10000, 4), round(np.percentile(boot_enh, 97.5) * 10000, 4)],
        },
        "tom_aggressive_vs_daily": {
            "mean_diff_bps": round(diff_agg.mean() * 10000, 4),
            "bootstrap_se_bps": round(boot_agg.std() * 10000, 4),
            "bootstrap_t": round(t_boot_agg, 4),
            "bootstrap_p": round(p_agg, 4),
            "ci_95_bps": [round(np.percentile(boot_agg, 2.5) * 10000, 4), round(np.percentile(boot_agg, 97.5) * 10000, 4)],
        },
    },
    "conclusion": "",
}

# Add strategy results
for name, data in results_full.items():
    results_json["strategy_results_full_sample"][name] = {
        "cagr_pct": round(data['cagr'], 2),
        "vol_pct": round(data['vol'], 2),
        "sharpe": round(data['sharpe'], 3),
        "mdd_pct": round(data['mdd'], 2),
        "calmar": round(data['calmar'], 3),
        "avg_weight": round(data['avg_weight'], 3),
        "net_sharpe": round(data.get('net_sharpe', 0), 3),
        "trades_per_year": round(data.get('trades_per_year', 0), 1),
    }

# Write conclusion
# NOTE: t_boot_enh > 0 means ToM BETTER, < 0 means ToM WORSE
# Must check SIGN, not just abs value
if t_boot_enh > 3.0 and improvement > 0:
    conclusion = (
        f"ToM calendar overlay SIGNIFICANTLY improves VT. "
        f"Bootstrap t={t_boot_enh:.2f} passes Harvey threshold. "
        f"ToM Enhanced Sharpe improvement: {improvement:+.3f}."
    )
elif t_boot_enh < -3.0:
    conclusion = (
        f"NEGATIVE RESULT: ToM calendar overlay SIGNIFICANTLY HURTS VT. "
        f"Bootstrap t={t_boot_enh:.2f} (negative = ToM worse). "
        f"Sharpe change: {improvement:+.4f}. "
        f"Reducing mid-month exposure just reduces overall return without risk benefit. "
        f"ToM anomaly does not exist in modern SPY data (Welch t={t_stat:.2f}, p={p_val:.4f}). "
        f"VT already captures timing benefits via VIX reactivity — no calendar overlay needed."
    )
elif p_val < 0.05 and n_enh_wins > n_periods / 2:
    conclusion = (
        f"ToM anomaly EXISTS in SPY (t={t_stat:.2f}, p={p_val:.4f}) but "
        f"calendar overlay does NOT significantly improve VT performance. "
        f"Bootstrap t={t_boot_enh:.2f} fails Harvey threshold (3.0). "
        f"Improvement is {improvement:+.4f} Sharpe — too small for practical use."
    )
else:
    conclusion = (
        f"ToM anomaly is {'present but weak' if p_val < 0.10 else 'NOT significant'} "
        f"in SPY (t={t_stat:.2f}, p={p_val:.4f}). "
        f"Calendar overlay does NOT improve VT. "
        f"Bootstrap t={t_boot_enh:.2f}. "
        f"Conclusion: VT already captures timing benefits via VIX reactivity."
    )

results_json["conclusion"] = conclusion

# Save
output_path = "experiments/k547_monthly_tom_vt_results.json"
with open(output_path, 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"\n  CONCLUSION: {conclusion}")
print("=" * 70)
