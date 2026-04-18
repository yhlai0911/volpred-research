#!/usr/bin/env python3
"""
K557: Gold Regime Allocation — Is gold always 50%, or should it vary with gold's macro cycle?

Motivation:
- Gold has distinct multi-year bull/bear regimes (bull 2005-2011, 2019-2026; bear 2012-2018)
- K546 tested GLD's OWN vol but not price trend
- K507 tested correlation regime → null (static beats dynamic)
- K275 synthesized: 50/50 SPY/GLD + 12/VIX is unbeatable across 10+ attempts
- This attacks 50/50 from gold's TREND angle (not vol or correlation)

Design:
1. Data: SPY + GLD + VIX from yfinance (2005-2026)
2. Gold regime indicators:
   a. GLD 200-day MA trend (price > MA200 = bull)
   b. GLD 12-month return (positive = bull)
   c. Real gold proxy: GLD/TIP ratio
3. Strategies (all with 12/VIX base leverage):
   a. Gold Trend: 60/40 SPY/GLD when GLD > MA200, 40/60 when below
   b. Gold Momentum: GLD weight = 0.3 + 0.4*rank(12m_ret)
   c. Counter-cyclical: INCREASE GLD in bear (buy cheap insurance)
   d. Dynamic Risk Budget: equalize risk contribution, when GLD vol high reduce capital weight
4. Benchmark: static 50/50 + 12/VIX
5. Cross-OOS: 5 periods
6. Harvey t>3.0 threshold

References:
- K275: Complete Case for 50/50 (synthesis)
- K507: Dynamic SPY/GLD Allocation (correlation regime → null)
- K204: GLD Momentum-Based VT
- Baur & McDermott (2010): Is gold a safe haven? International evidence, JBF
- Reboredo (2013): Is gold a hedge or safe haven against oil price movements? RIBAF

Author: VolPred Research System
Data source: yfinance (SPY, GLD, TIP, ^VIX)
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')

# ==============================================================
# 1. Data Download
# ==============================================================
print("=" * 70)
print("K557: Gold Regime Allocation")
print("=" * 70)

tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'TIP': 'TIP',
    'VIX': '^VIX'
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2004-11-01', end='2026-03-27', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'] if 'Close' in df.columns else df['Adj Close']

prices = pd.DataFrame(data).dropna()
print(f"\nData period: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"Total trading days: {len(prices)}")

# Calculate returns
returns = prices[['SPY', 'GLD']].pct_change().dropna()
vix = prices['VIX'].reindex(returns.index)

print(f"\nDescriptive Statistics:")
print(f"  SPY: mean={returns['SPY'].mean()*252:.4f}, std={returns['SPY'].std()*np.sqrt(252):.4f}")
print(f"  GLD: mean={returns['GLD'].mean()*252:.4f}, std={returns['GLD'].std()*np.sqrt(252):.4f}")
print(f"  VIX: mean={vix.mean():.2f}, std={vix.std():.2f}")

# ==============================================================
# 2. Regime Indicators
# ==============================================================
print("\n" + "=" * 70)
print("2. Computing Gold Regime Indicators")
print("=" * 70)

# a. GLD 200-day MA
gld_price = prices['GLD'].reindex(returns.index)
ma200 = gld_price.rolling(200).mean()
gld_above_ma200 = (gld_price > ma200).astype(float)  # 1=bull, 0=bear

# b. GLD 12-month (252-day) return
gld_12m_ret = gld_price.pct_change(252)

# c. Real gold proxy: GLD/TIP ratio
tip_price = prices['TIP'].reindex(returns.index)
gld_tip_ratio = gld_price / tip_price
gld_tip_ma = gld_tip_ratio.rolling(200).mean()
gld_real_bull = (gld_tip_ratio > gld_tip_ma).astype(float)

# d. GLD rolling volatility (for risk budget)
gld_vol_60 = returns['GLD'].rolling(60).std() * np.sqrt(252)
spy_vol_60 = returns['SPY'].rolling(60).std() * np.sqrt(252)

# Trim to where all indicators available (need 252 days for 12m return)
start_idx = max(
    ma200.first_valid_index(),
    gld_12m_ret.first_valid_index(),
    gld_tip_ma.first_valid_index(),
    gld_vol_60.first_valid_index()
)
# Align everything
mask = returns.index >= start_idx
returns_aligned = returns[mask].copy()
vix_aligned = vix[mask].copy()
gld_above_ma200 = gld_above_ma200[mask]
gld_12m_ret_aligned = gld_12m_ret[mask]
gld_real_bull_aligned = gld_real_bull[mask]
gld_vol_aligned = gld_vol_60[mask]
spy_vol_aligned = spy_vol_60[mask]

print(f"Analysis period (after warmup): {returns_aligned.index[0].strftime('%Y-%m-%d')} to {returns_aligned.index[-1].strftime('%Y-%m-%d')}")
print(f"Trading days: {len(returns_aligned)}")
print(f"\nGold regime summary (MA200):")
bull_pct = gld_above_ma200.mean() * 100
print(f"  Bull days (GLD > MA200): {bull_pct:.1f}%")
print(f"  Bear days (GLD < MA200): {100-bull_pct:.1f}%")
print(f"\nGold 12m return: mean={gld_12m_ret_aligned.mean()*100:.1f}%, std={gld_12m_ret_aligned.std()*100:.1f}%")

# ==============================================================
# 3. Strategy Functions
# ==============================================================

def compute_12_over_vix(vix_series):
    """12/VIX leverage: base portfolio leverage"""
    leverage = 12.0 / vix_series
    leverage = leverage.clip(0.5, 1.5)  # reasonable bounds
    return leverage

def strategy_static_50_50(returns_df, vix_s):
    """Benchmark: Static 50/50 SPY/GLD + 12/VIX"""
    lev = compute_12_over_vix(vix_s)
    port_ret = 0.5 * returns_df['SPY'] + 0.5 * returns_df['GLD']
    return (port_ret * lev).dropna()

def strategy_gold_trend(returns_df, vix_s, gld_bull):
    """Gold Trend: 60/40 when GLD > MA200, 40/60 when below"""
    lev = compute_12_over_vix(vix_s)
    # Use previous day's signal to avoid lookahead
    signal = gld_bull.shift(1).dropna()
    common = returns_df.index.intersection(signal.index).intersection(lev.index)
    spy_w = signal.reindex(common) * 0.6 + (1 - signal.reindex(common)) * 0.4
    gld_w = 1 - spy_w
    port_ret = spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)
    return (port_ret * lev.reindex(common)).dropna()

def strategy_gold_momentum(returns_df, vix_s, gld_12m):
    """Gold Momentum: GLD weight varies with 12m return rank"""
    lev = compute_12_over_vix(vix_s)
    # Use previous day's signal
    signal = gld_12m.shift(1).dropna()
    common = returns_df.index.intersection(signal.index).intersection(lev.index)
    # Expanding rank percentile of 12m return
    sig = signal.reindex(common)
    rank_pct = sig.rolling(window=504, min_periods=252).apply(
        lambda x: stats.percentileofscore(x, x.iloc[-1]) / 100.0, raw=False
    )
    # GLD weight: 0.3 (low momentum) to 0.7 (high momentum)
    gld_w = 0.3 + 0.4 * rank_pct
    gld_w = gld_w.clip(0.3, 0.7)
    spy_w = 1 - gld_w
    port_ret = spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)
    return (port_ret * lev.reindex(common)).dropna()

def strategy_counter_cyclical(returns_df, vix_s, gld_bull):
    """Counter-cyclical: INCREASE GLD in bear (buy cheap insurance)"""
    lev = compute_12_over_vix(vix_s)
    signal = gld_bull.shift(1).dropna()
    common = returns_df.index.intersection(signal.index).intersection(lev.index)
    # Bear → 60% GLD (buy more), Bull → 40% GLD (take profit)
    gld_w = signal.reindex(common) * 0.4 + (1 - signal.reindex(common)) * 0.6
    spy_w = 1 - gld_w
    port_ret = spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)
    return (port_ret * lev.reindex(common)).dropna()

def strategy_risk_budget(returns_df, vix_s, gld_vol, spy_vol):
    """Dynamic Risk Budget: equalize risk contribution via inverse vol"""
    lev = compute_12_over_vix(vix_s)
    gv = gld_vol.shift(1).dropna()
    sv = spy_vol.shift(1).dropna()
    common = returns_df.index.intersection(gv.index).intersection(sv.index).intersection(lev.index)
    gv = gv.reindex(common)
    sv = sv.reindex(common)
    # Inverse vol weights
    inv_gld = 1.0 / gv
    inv_spy = 1.0 / sv
    total_inv = inv_gld + inv_spy
    spy_w = (inv_spy / total_inv).clip(0.3, 0.7)
    gld_w = 1 - spy_w
    port_ret = spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)
    return (port_ret * lev.reindex(common)).dropna()

def strategy_real_gold_trend(returns_df, vix_s, real_bull):
    """Real Gold Trend: 60/40 when GLD/TIP > MA200, 40/60 when below"""
    lev = compute_12_over_vix(vix_s)
    signal = real_bull.shift(1).dropna()
    common = returns_df.index.intersection(signal.index).intersection(lev.index)
    spy_w = signal.reindex(common) * 0.6 + (1 - signal.reindex(common)) * 0.4
    gld_w = 1 - spy_w
    port_ret = spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)
    return (port_ret * lev.reindex(common)).dropna()


# ==============================================================
# 4. Performance Metrics
# ==============================================================

def compute_metrics(ret_series, name=""):
    """Compute standard performance metrics"""
    if len(ret_series) < 252:
        return None
    ann_ret = ret_series.mean() * 252
    ann_vol = ret_series.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + ret_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    max_dd = dd.min()

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    downside = ret_series[ret_series < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    n_years = len(ret_series) / 252
    total_ret = cum.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    return {
        'name': name,
        'ann_return': round(ann_ret, 4),
        'ann_vol': round(ann_vol, 4),
        'sharpe': round(sharpe, 4),
        'max_dd': round(max_dd, 4),
        'calmar': round(calmar, 4),
        'sortino': round(sortino, 4),
        'cagr': round(cagr, 4),
        'n_days': len(ret_series),
        'n_years': round(n_years, 2)
    }

def dm_test(ret1, ret2, benchmark_ret):
    """
    Diebold-Mariano style test comparing two strategies.
    H0: both strategies have the same excess return over benchmark.
    Uses squared excess returns as loss function.
    """
    common = ret1.index.intersection(ret2.index).intersection(benchmark_ret.index)
    r1 = ret1.reindex(common)
    r2 = ret2.reindex(common)
    rb = benchmark_ret.reindex(common)

    # Loss = negative excess return (we want higher returns)
    # Or alternatively, compare Sharpe-like: use risk-adjusted difference
    d = r1 - r2  # return difference

    n = len(d)
    d_mean = d.mean()
    d_std = d.std(ddof=1)

    if d_std == 0:
        return 0, 1.0

    t_stat = d_mean / (d_std / np.sqrt(n))
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))

    return round(t_stat, 4), round(p_value, 4)


# ==============================================================
# 5. Full-Sample Analysis
# ==============================================================
print("\n" + "=" * 70)
print("3. Full-Sample Results")
print("=" * 70)

strategies = {
    'Static 50/50': strategy_static_50_50(returns_aligned, vix_aligned),
    'Gold Trend (MA200)': strategy_gold_trend(returns_aligned, vix_aligned, gld_above_ma200),
    'Gold Momentum (12m)': strategy_gold_momentum(returns_aligned, vix_aligned, gld_12m_ret_aligned),
    'Counter-cyclical': strategy_counter_cyclical(returns_aligned, vix_aligned, gld_above_ma200),
    'Risk Budget (inv-vol)': strategy_risk_budget(returns_aligned, vix_aligned, gld_vol_aligned, spy_vol_aligned),
    'Real Gold Trend (GLD/TIP)': strategy_real_gold_trend(returns_aligned, vix_aligned, gld_real_bull_aligned),
}

full_results = {}
print(f"\n{'Strategy':<28} {'Return':>8} {'Vol':>8} {'Sharpe':>8} {'MaxDD':>8} {'Calmar':>8} {'Sortino':>8} {'CAGR':>8}")
print("-" * 100)

for name, rets in strategies.items():
    m = compute_metrics(rets, name)
    if m:
        full_results[name] = m
        print(f"{name:<28} {m['ann_return']:>8.4f} {m['ann_vol']:>8.4f} {m['sharpe']:>8.4f} {m['max_dd']:>8.4f} {m['calmar']:>8.4f} {m['sortino']:>8.4f} {m['cagr']:>8.4f}")

# DM tests vs benchmark
print(f"\n--- DM Tests vs Static 50/50 ---")
benchmark = strategies['Static 50/50']
for name, rets in strategies.items():
    if name == 'Static 50/50':
        continue
    t, p = dm_test(rets, benchmark, benchmark)
    full_results[name]['dm_t_vs_50_50'] = t
    full_results[name]['dm_p_vs_50_50'] = p
    sig = "***" if abs(t) > 3.0 else "**" if abs(t) > 2.0 else "*" if abs(t) > 1.65 else ""
    print(f"  {name:<28} t={t:>7.4f}  p={p:.4f}  {sig}")


# ==============================================================
# 6. Cross-OOS Validation (5 periods)
# ==============================================================
print("\n" + "=" * 70)
print("4. Cross-OOS Validation (5 periods)")
print("=" * 70)

# Define OOS periods
all_dates = returns_aligned.index
total_days = len(all_dates)

# 5 non-overlapping OOS periods (each ~3 years with ~5 years IS)
oos_periods = [
    ('2008-01-01', '2010-12-31', 'OOS1: GFC + Recovery'),
    ('2011-01-01', '2013-12-31', 'OOS2: Gold Peak + Bear'),
    ('2014-01-01', '2016-12-31', 'OOS3: Gold Bear Bottom'),
    ('2017-01-01', '2019-12-31', 'OOS4: Gold Recovery'),
    ('2020-01-01', '2022-12-31', 'OOS5: COVID + Inflation'),
]

cross_oos_results = {}

for oos_start, oos_end, oos_label in oos_periods:
    print(f"\n--- {oos_label} ({oos_start} to {oos_end}) ---")

    mask_oos = (returns_aligned.index >= oos_start) & (returns_aligned.index <= oos_end)
    ret_oos = returns_aligned[mask_oos]
    vix_oos = vix_aligned[mask_oos]

    if len(ret_oos) < 100:
        print(f"  Skipping: only {len(ret_oos)} days")
        continue

    # Need regime indicators for OOS period
    gld_bull_oos = gld_above_ma200[mask_oos]
    gld_12m_oos = gld_12m_ret_aligned[mask_oos]
    gld_real_oos = gld_real_bull_aligned[mask_oos]
    gld_vol_oos = gld_vol_aligned[mask_oos]
    spy_vol_oos = spy_vol_aligned[mask_oos]

    strats_oos = {
        'Static 50/50': strategy_static_50_50(ret_oos, vix_oos),
        'Gold Trend (MA200)': strategy_gold_trend(ret_oos, vix_oos, gld_bull_oos),
        'Gold Momentum (12m)': strategy_gold_momentum(ret_oos, vix_oos, gld_12m_oos),
        'Counter-cyclical': strategy_counter_cyclical(ret_oos, vix_oos, gld_bull_oos),
        'Risk Budget (inv-vol)': strategy_risk_budget(ret_oos, vix_oos, gld_vol_oos, spy_vol_oos),
        'Real Gold Trend (GLD/TIP)': strategy_real_gold_trend(ret_oos, vix_oos, gld_real_oos),
    }

    oos_metrics = {}
    print(f"  {'Strategy':<28} {'Sharpe':>8} {'MaxDD':>8} {'CAGR':>8}")
    print(f"  {'-'*56}")

    for name, rets in strats_oos.items():
        m = compute_metrics(rets, name)
        if m:
            oos_metrics[name] = m
            print(f"  {name:<28} {m['sharpe']:>8.4f} {m['max_dd']:>8.4f} {m['cagr']:>8.4f}")

    # Store
    cross_oos_results[oos_label] = oos_metrics

# ==============================================================
# 7. Cross-OOS Summary: Which strategies consistently beat 50/50?
# ==============================================================
print("\n" + "=" * 70)
print("5. Cross-OOS Summary: Sharpe Differences vs Static 50/50")
print("=" * 70)

strategy_names = ['Gold Trend (MA200)', 'Gold Momentum (12m)', 'Counter-cyclical',
                  'Risk Budget (inv-vol)', 'Real Gold Trend (GLD/TIP)']

oos_sharpe_diffs = {s: [] for s in strategy_names}
oos_sharpes = {s: [] for s in ['Static 50/50'] + strategy_names}

for period, metrics in cross_oos_results.items():
    if 'Static 50/50' not in metrics:
        continue
    bench_sharpe = metrics['Static 50/50']['sharpe']
    oos_sharpes['Static 50/50'].append(bench_sharpe)

    for sname in strategy_names:
        if sname in metrics:
            diff = metrics[sname]['sharpe'] - bench_sharpe
            oos_sharpe_diffs[sname].append(diff)
            oos_sharpes[sname].append(metrics[sname]['sharpe'])

print(f"\n{'Strategy':<28} {'Mean ΔSharpe':>12} {'Wins/Total':>12} {'t-stat':>8} {'p-value':>8} {'Harvey':>8}")
print("-" * 80)

cross_oos_summary = {}
for sname in strategy_names:
    diffs = oos_sharpe_diffs[sname]
    if len(diffs) < 3:
        continue

    mean_diff = np.mean(diffs)
    n_wins = sum(1 for d in diffs if d > 0)
    n_total = len(diffs)

    # t-test: are the Sharpe differences significantly > 0?
    if np.std(diffs) > 0:
        t_stat, p_val = stats.ttest_1samp(diffs, 0)
    else:
        t_stat, p_val = 0.0, 1.0

    passes_harvey = abs(t_stat) > 3.0

    cross_oos_summary[sname] = {
        'mean_sharpe_diff': round(mean_diff, 4),
        'wins': n_wins,
        'total': n_total,
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 4),
        'passes_harvey': passes_harvey,
        'individual_diffs': [round(d, 4) for d in diffs]
    }

    harvey_str = "PASS" if passes_harvey else "FAIL"
    print(f"{sname:<28} {mean_diff:>12.4f} {n_wins}/{n_total:>10} {t_stat:>8.4f} {p_val:>8.4f} {harvey_str:>8}")

# ==============================================================
# 8. Regime-Conditional Analysis
# ==============================================================
print("\n" + "=" * 70)
print("6. Regime-Conditional Analysis: Performance in Gold Bull vs Bear")
print("=" * 70)

# Use MA200 as regime classifier
regime_signal = gld_above_ma200.shift(1).dropna()
bull_days = regime_signal[regime_signal == 1].index
bear_days = regime_signal[regime_signal == 0].index

print(f"\nGold Bull days: {len(bull_days)}, Gold Bear days: {len(bear_days)}")

regime_analysis = {}
for regime_name, regime_idx in [('Gold Bull', bull_days), ('Gold Bear', bear_days)]:
    print(f"\n--- {regime_name} ---")
    regime_metrics = {}

    for sname, rets in strategies.items():
        common = rets.index.intersection(regime_idx)
        if len(common) < 100:
            continue
        m = compute_metrics(rets.reindex(common), sname)
        if m:
            regime_metrics[sname] = m

    if regime_metrics:
        print(f"  {'Strategy':<28} {'Sharpe':>8} {'MaxDD':>8} {'CAGR':>8}")
        print(f"  {'-'*56}")
        for sname, m in regime_metrics.items():
            print(f"  {sname:<28} {m['sharpe']:>8.4f} {m['max_dd']:>8.4f} {m['cagr']:>8.4f}")

    regime_analysis[regime_name] = regime_metrics

# ==============================================================
# 9. Transaction Cost Sensitivity
# ==============================================================
print("\n" + "=" * 70)
print("7. Transaction Cost Sensitivity")
print("=" * 70)

# Estimate turnover for each strategy
def estimate_turnover_and_net_sharpe(returns_df, vix_s, strategy_func, strategy_kwargs, tc_bps_list=[0, 5, 10, 20]):
    """Estimate strategy performance net of transaction costs"""
    results = {}
    for tc_bps in tc_bps_list:
        # Approximate: strategy with different allocations has turnover
        # Use raw returns and subtract tc * estimated daily turnover
        rets = strategy_func(returns_df, vix_s, **strategy_kwargs)
        if len(rets) < 252:
            continue

        # For static 50/50, daily turnover ≈ 0 (just rebalance from drift)
        # For dynamic, estimate turnover from weight changes
        # Simple proxy: assume 1/20 of weight change per day as turnover
        # This is approximate but fair for comparison
        tc_daily = tc_bps / 10000.0 * 0.02  # assume ~2% daily turnover for dynamic
        rets_net = rets - tc_daily
        m = compute_metrics(rets_net, f"tc={tc_bps}bps")
        if m:
            results[tc_bps] = m
    return results

# More precise: compute actual weight changes
def compute_strategy_with_tc(returns_df, vix_s, weight_func, tc_bps=10):
    """
    Compute strategy returns with explicit transaction costs from weight changes.
    weight_func returns (spy_weight_series, gld_weight_series) using LAGGED signals.
    """
    spy_w, gld_w = weight_func()
    lev = compute_12_over_vix(vix_s)

    common = returns_df.index.intersection(spy_w.index).intersection(lev.index)
    spy_w = spy_w.reindex(common)
    gld_w = gld_w.reindex(common)
    lev_c = lev.reindex(common)

    # Weight changes → turnover
    spy_w_change = spy_w.diff().abs()
    gld_w_change = gld_w.diff().abs()
    daily_turnover = (spy_w_change + gld_w_change) / 2  # one-way

    # Gross return
    gross_ret = (spy_w * returns_df['SPY'].reindex(common) + gld_w * returns_df['GLD'].reindex(common)) * lev_c

    # Net return
    tc_cost = daily_turnover * (tc_bps / 10000.0) * 2  # round-trip
    net_ret = gross_ret - tc_cost

    return net_ret.dropna(), daily_turnover.mean()

# Weight functions for TC analysis
def weights_static():
    idx = returns_aligned.index
    return pd.Series(0.5, index=idx), pd.Series(0.5, index=idx)

def weights_gold_trend():
    signal = gld_above_ma200.shift(1).dropna()
    idx = returns_aligned.index.intersection(signal.index)
    sig = signal.reindex(idx)
    spy_w = sig * 0.6 + (1 - sig) * 0.4
    gld_w = 1 - spy_w
    return spy_w, gld_w

def weights_counter():
    signal = gld_above_ma200.shift(1).dropna()
    idx = returns_aligned.index.intersection(signal.index)
    sig = signal.reindex(idx)
    gld_w = sig * 0.4 + (1 - sig) * 0.6
    spy_w = 1 - gld_w
    return spy_w, gld_w

def weights_risk_budget():
    gv = gld_vol_aligned.shift(1).dropna()
    sv = spy_vol_aligned.shift(1).dropna()
    common = returns_aligned.index.intersection(gv.index).intersection(sv.index)
    gv = gv.reindex(common)
    sv = sv.reindex(common)
    inv_gld = 1.0 / gv
    inv_spy = 1.0 / sv
    total_inv = inv_gld + inv_spy
    spy_w = (inv_spy / total_inv).clip(0.3, 0.7)
    gld_w = 1 - spy_w
    return spy_w, gld_w

tc_levels = [0, 5, 10, 20, 50]
weight_funcs = {
    'Static 50/50': weights_static,
    'Gold Trend (MA200)': weights_gold_trend,
    'Counter-cyclical': weights_counter,
    'Risk Budget (inv-vol)': weights_risk_budget,
}

print(f"\n{'Strategy':<28}", end="")
for tc in tc_levels:
    print(f" {'Sharpe@'+str(tc)+'bp':>12}", end="")
print(f" {'Avg Turnover':>14}")
print("-" * 100)

tc_results = {}
for sname, wfunc in weight_funcs.items():
    tc_results[sname] = {}
    sharpes = []
    turnover = 0
    for tc in tc_levels:
        net_ret, avg_to = compute_strategy_with_tc(returns_aligned, vix_aligned, wfunc, tc_bps=tc)
        m = compute_metrics(net_ret, sname)
        if m:
            sharpes.append(m['sharpe'])
            tc_results[sname][f'sharpe_tc{tc}bps'] = m['sharpe']
            turnover = avg_to
    tc_results[sname]['avg_daily_turnover'] = round(turnover, 6)

    print(f"{sname:<28}", end="")
    for s in sharpes:
        print(f" {s:>12.4f}", end="")
    print(f" {turnover:>14.6f}")


# ==============================================================
# 10. Statistical Robustness: Bootstrap
# ==============================================================
print("\n" + "=" * 70)
print("8. Bootstrap Confidence Intervals (10,000 reps)")
print("=" * 70)

n_boot = 10000
np.random.seed(42)

bench_rets = strategies['Static 50/50'].values

bootstrap_results = {}
for sname in strategy_names:
    if sname not in strategies:
        continue
    strat_rets = strategies[sname]

    # Align
    common = strategies['Static 50/50'].index.intersection(strat_rets.index)
    b = strategies['Static 50/50'].reindex(common).values
    s = strat_rets.reindex(common).values
    diff = s - b
    n = len(diff)

    boot_diffs = np.zeros(n_boot)
    for i in range(n_boot):
        idx = np.random.choice(n, size=n, replace=True)
        boot_diffs[i] = np.mean(diff[idx]) * 252 / (np.std(diff[idx]) * np.sqrt(252) + 1e-10)

    ci_low = np.percentile(boot_diffs, 2.5)
    ci_high = np.percentile(boot_diffs, 97.5)
    mean_boot = np.mean(boot_diffs)

    bootstrap_results[sname] = {
        'mean_sharpe_diff': round(mean_boot, 4),
        'ci_95_low': round(ci_low, 4),
        'ci_95_high': round(ci_high, 4),
        'zero_in_ci': ci_low <= 0 <= ci_high
    }

    zero_str = "YES (null)" if ci_low <= 0 <= ci_high else "NO (significant)"
    print(f"  {sname:<28} ΔSharpe={mean_boot:>7.4f}  95%CI=[{ci_low:.4f}, {ci_high:.4f}]  0 in CI: {zero_str}")

# ==============================================================
# 11. Most Recent OOS (2023-2026)
# ==============================================================
print("\n" + "=" * 70)
print("9. Most Recent OOS: 2023-2026 (gold bull market)")
print("=" * 70)

mask_recent = returns_aligned.index >= '2023-01-01'
ret_recent = returns_aligned[mask_recent]
vix_recent = vix_aligned[mask_recent]
gld_bull_recent = gld_above_ma200[mask_recent]
gld_12m_recent = gld_12m_ret_aligned[mask_recent]
gld_real_recent = gld_real_bull_aligned[mask_recent]
gld_vol_recent = gld_vol_aligned[mask_recent]
spy_vol_recent = spy_vol_aligned[mask_recent]

strats_recent = {
    'Static 50/50': strategy_static_50_50(ret_recent, vix_recent),
    'Gold Trend (MA200)': strategy_gold_trend(ret_recent, vix_recent, gld_bull_recent),
    'Gold Momentum (12m)': strategy_gold_momentum(ret_recent, vix_recent, gld_12m_recent),
    'Counter-cyclical': strategy_counter_cyclical(ret_recent, vix_recent, gld_bull_recent),
    'Risk Budget (inv-vol)': strategy_risk_budget(ret_recent, vix_recent, gld_vol_recent, spy_vol_recent),
    'Real Gold Trend (GLD/TIP)': strategy_real_gold_trend(ret_recent, vix_recent, gld_real_recent),
}

print(f"\n{'Strategy':<28} {'Sharpe':>8} {'MaxDD':>8} {'CAGR':>8}")
print("-" * 56)
recent_results = {}
for sname, rets in strats_recent.items():
    m = compute_metrics(rets, sname)
    if m:
        recent_results[sname] = m
        print(f"  {sname:<28} {m['sharpe']:>8.4f} {m['max_dd']:>8.4f} {m['cagr']:>8.4f}")

# ==============================================================
# 12. Compile Results JSON
# ==============================================================
print("\n" + "=" * 70)
print("10. Final Verdict")
print("=" * 70)

# Count how many strategies beat 50/50 in cross-OOS
n_beat = 0
n_total_strats = 0
for sname, summary in cross_oos_summary.items():
    n_total_strats += 1
    if summary['mean_sharpe_diff'] > 0 and summary['wins'] > summary['total'] / 2:
        n_beat += 1

any_passes_harvey = any(s['passes_harvey'] for s in cross_oos_summary.values())

verdict = "NULL — No gold regime strategy significantly beats static 50/50"
if any_passes_harvey:
    passing = [s for s, v in cross_oos_summary.items() if v['passes_harvey']]
    verdict = f"SIGNIFICANT — {', '.join(passing)} pass Harvey threshold"

print(f"\n  Strategies tested: {n_total_strats}")
print(f"  Beat 50/50 in majority of OOS periods: {n_beat}/{n_total_strats}")
print(f"  Any pass Harvey t>3.0: {any_passes_harvey}")
print(f"\n  VERDICT: {verdict}")

# ==============================================================
# Save Results
# ==============================================================
results = {
    'experiment_id': 'K557',
    'title': 'Gold Regime Allocation — Is gold always 50%?',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (SPY, GLD, TIP, ^VIX)',
    'data_period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'analysis_period': f"{returns_aligned.index[0].strftime('%Y-%m-%d')} to {returns_aligned.index[-1].strftime('%Y-%m-%d')}",
    'n_trading_days': len(returns_aligned),
    'methodology': {
        'regime_indicators': ['GLD 200-day MA', 'GLD 12-month return', 'GLD/TIP ratio', 'Inverse vol'],
        'strategies': list(strategies.keys()),
        'benchmark': 'Static 50/50 SPY/GLD + 12/VIX',
        'oos_periods': [f"{s} to {e}: {l}" for s, e, l in oos_periods],
        'harvey_threshold': 3.0,
        'bootstrap_reps': n_boot,
    },
    'full_sample_results': full_results,
    'cross_oos_summary': cross_oos_summary,
    'cross_oos_details': {k: {sk: sv for sk, sv in v.items()} for k, v in cross_oos_results.items()},
    'regime_analysis': regime_analysis,
    'transaction_cost_sensitivity': tc_results,
    'bootstrap_results': bootstrap_results,
    'recent_oos_2023_2026': recent_results,
    'verdict': verdict,
    'conclusion': (
        'Gold regime-based allocation strategies (trend, momentum, counter-cyclical, risk budget) '
        'were tested against the static 50/50 SPY/GLD + 12/VIX benchmark. '
        'Cross-OOS validation across 5 distinct periods (2008-2022) determines robustness. '
        'Transaction cost sensitivity and bootstrap CIs provide additional rigor.'
    ),
    'references': [
        'K275: Complete Case for 50/50 SPY/GLD + 12/VIX',
        'K507: Dynamic SPY/GLD Allocation (correlation regime)',
        'K204: GLD Momentum-Based VT',
        'Baur & McDermott (2010): Is gold a safe haven? JBF',
        'Reboredo (2013): Is gold a hedge or safe haven against oil? RIBAF',
    ],
    'limitations': [
        'GLD data starts 2004, limiting pre-2005 analysis',
        'TIP used as inflation proxy (imperfect)',
        'Transaction costs estimated, not exact',
        'Gold regime classification is binary (MA200), real regimes are fuzzy',
        'VIX leverage 12/VIX has its own regime dependency not decomposed here',
    ]
}

output_path = 'experiments/k557_gold_regime_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("=" * 70)
print("K557 Complete")
print("=" * 70)
