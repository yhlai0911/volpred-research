#!/usr/bin/env python3
"""
K563: Weekly Sector Momentum VT — Can Weekly Rebalancing Capture Sector Momentum Alpha?
========================================================================================

Motivation:
K562 showed daily sector momentum Sharpe 2.157 but monthly Sharpe 1.228 (worse than
benchmark). The gap between daily and monthly is huge. Weekly was NOT tested in K562's
rebalancing sensitivity (only daily/monthly). Weekly might be the sweet spot — frequent
enough to capture momentum but infrequent enough to be practical.

Prior knowledge:
- K562: Daily sector momentum Sharpe 2.157, Monthly 1.228 (worse than benchmark)
- K58: Sector VT Map — all 11 sectors benefit from VT, gamma too narrow for sector-level
- K243: Sector Rotation — Harvey PASS (t=3.99) but DM NS, MDD -37%
- K244: TSMOM+Sector — absorbed by VT
- K247: Dual Momentum — degraded 53%
- K556: Momentum Crash Filter — momentum overlays on VT mostly NULL
- K524: 384 rules, 0 survive BH correction — momentum timing is notoriously hard

Design:
1. Data: SPY + 8 sector ETFs + GLD + VIX from yfinance (2005-2026)
2. Weekly rebalancing: every Friday, select top sectors by momentum
3. Test variants:
   a. Weekly top-1 momentum (60d lookback)
   b. Weekly top-1 momentum (20d lookback — K562 showed 20d best for daily)
   c. Weekly top-2 equal weight
   d. Weekly top-1 with 2-week hold (avoid whipsaw)
   e. Bi-weekly rebalancing (every other Friday)
4. Benchmark: static SPY VT + GLD (daily rebalanced 12/VIX)
5. TX costs: 5bp per trade (realistic for sector ETFs)
6. Cross-OOS: 5 periods
7. Harvey t>3.0
8. Compare weekly Sharpe vs K562's daily (2.157) and monthly (1.228)

Key question: Is there a rebalancing frequency between daily and monthly where sector
momentum adds genuine alpha (not just turnover artifact)?

Literature:
- Jegadeesh & Titman (1993): "Returns to Buying Winners and Selling Losers", JF
- Moskowitz & Grinblatt (1999): "Do Industries Explain Momentum?", JF
- Moreira & Muir (2017): "Volatility-Managed Portfolios", JF
- Barroso & Santa-Clara (2015): "Momentum has its moments", JFE
- Harvey, Liu & Zhu (2016): "...and the Cross-Section of Expected Returns", RFS
- O'Neal (2000): "Industry Momentum and Sector Mutual Funds", Financial Analysts Journal

Data source: yfinance (SPY, ^VIX, GLD, XLK, XLF, XLV, XLE, XLI, XLY, XLP, XLU)
Period: 2005-01 to 2026-03
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

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K563: Weekly Sector Momentum VT")
print("=" * 70)

tickers = {
    'SPY': 'SPY',
    'GLD': 'GLD',
    'VIX': '^VIX',
    'XLK': 'XLK',  # Technology
    'XLF': 'XLF',  # Financials
    'XLV': 'XLV',  # Healthcare
    'XLE': 'XLE',  # Energy
    'XLI': 'XLI',  # Industrials
    'XLY': 'XLY',  # Consumer Discretionary
    'XLP': 'XLP',  # Consumer Staples
    'XLU': 'XLU',  # Utilities
}

sector_etfs = ['XLK', 'XLF', 'XLV', 'XLE', 'XLI', 'XLY', 'XLP', 'XLU']

print("\n[1] Downloading data (2005-2026)...")
data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2005-01-01', end='2026-03-27', progress=False)
    if hasattr(df.columns, 'droplevel') and isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    data[name] = df['Close'] if name == 'VIX' else df['Adj Close'] if 'Adj Close' in df.columns else df['Close']
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align all data
prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"\nAligned data: {len(prices)} rows, {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

# Compute daily returns
returns = prices[['SPY', 'GLD'] + sector_etfs].pct_change().dropna()
vix = prices['VIX'].reindex(returns.index)

print(f"Returns: {len(returns)} days")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n" + "=" * 70)
print("[2] Descriptive Statistics — Sector ETF Returns")
print("=" * 70)

desc_stats = {}
for col in sector_etfs + ['SPY', 'GLD']:
    r = returns[col]
    desc_stats[col] = {
        'mean_ann': float(r.mean() * 252),
        'std_ann': float(r.std() * np.sqrt(252)),
        'sharpe_bh': float(r.mean() / r.std() * np.sqrt(252)),
        'skew': float(r.skew()),
        'kurtosis': float(r.kurtosis()),
        'min': float(r.min()),
        'max': float(r.max()),
    }
    print(f"  {col}: Ann Return={desc_stats[col]['mean_ann']:.3f}, "
          f"Ann Vol={desc_stats[col]['std_ann']:.3f}, "
          f"Sharpe(B&H)={desc_stats[col]['sharpe_bh']:.3f}, "
          f"Skew={desc_stats[col]['skew']:.3f}, "
          f"Kurt={desc_stats[col]['kurtosis']:.3f}")

# ============================================================
# 3. Identify Fridays (weekly rebalancing dates)
# ============================================================
print("\n" + "=" * 70)
print("[3] Identify Rebalancing Dates")
print("=" * 70)

# Friday = dayofweek 4
fridays = returns.index[returns.index.dayofweek == 4]
print(f"  Total Fridays: {len(fridays)}")
print(f"  First: {fridays[0].strftime('%Y-%m-%d')}, Last: {fridays[-1].strftime('%Y-%m-%d')}")

# Bi-weekly: every other Friday
bi_weekly = fridays[::2]
print(f"  Bi-weekly Fridays: {len(bi_weekly)}")


# ============================================================
# 4. Strategy Implementations
# ============================================================
def compute_vt_benchmark(returns_df, vix_series):
    """Static SPY+GLD VT benchmark: 12/VIX weight on SPY, rest on GLD, daily rebal."""
    spy_ret = returns_df['SPY']
    gld_ret = returns_df['GLD']
    vix_prev = vix_series.shift(1)
    w_spy = (12.0 / vix_prev).clip(0, 1)
    port_ret = w_spy * spy_ret + (1 - w_spy) * gld_ret
    return port_ret


def compute_sector_momentum_weekly(returns_df, vix_series, prices_df,
                                    rebal_dates, lookback_days=60,
                                    top_n=1, hold_weeks=1,
                                    tx_cost_bp=5):
    """
    Weekly sector momentum + VT overlay.

    On each rebalancing date:
    1. Rank sectors by lookback-day momentum (cumulative return)
    2. Select top_n sectors
    3. Apply VT: w = 12/VIX allocated equally among top sectors, rest to GLD
    4. Hold for hold_weeks weeks
    5. Deduct TX costs on position changes
    """
    sector_prices = prices_df[sector_etfs]
    spy_ret = returns_df['SPY']
    gld_ret = returns_df['GLD']
    all_dates = returns_df.index

    # Pre-compute sector momentums for all dates
    sector_momentum = sector_prices.pct_change(lookback_days)

    port_returns = pd.Series(0.0, index=all_dates)

    # Track current holdings
    current_sectors = []
    last_rebal_idx = -999  # index into rebal_dates
    hold_counter = 0

    # Build a set for quick lookup
    rebal_set = set(rebal_dates)

    # For each day, determine which sectors are held
    holdings_history = {}  # date -> list of sectors

    active_sectors = []
    for i, date in enumerate(all_dates):
        # Check if it's a rebalancing date and hold period expired
        is_rebal = date in rebal_set

        if is_rebal and hold_counter <= 0:
            # Get momentum for this date
            mom = sector_momentum.loc[date] if date in sector_momentum.index else None
            if mom is not None and not mom.isna().all():
                mom_clean = mom.dropna()
                if len(mom_clean) >= top_n:
                    new_sectors = mom_clean.nlargest(top_n).index.tolist()
                    active_sectors = new_sectors
                    hold_counter = hold_weeks

        if is_rebal:
            hold_counter -= 1

        holdings_history[date] = active_sectors.copy()

    # Now compute returns day by day
    prev_sectors = []
    for i, date in enumerate(all_dates):
        held = holdings_history.get(date, [])
        if len(held) == 0:
            # Fallback: use SPY VT
            vix_val = vix_series.shift(1).get(date, 20)
            if pd.isna(vix_val) or vix_val <= 0:
                vix_val = 20
            w_eq = min(12.0 / vix_val, 1.0)
            port_returns.iloc[i] = w_eq * spy_ret.iloc[i] + (1 - w_eq) * gld_ret.iloc[i]
        else:
            vix_val = vix_series.shift(1).get(date, 20)
            if pd.isna(vix_val) or vix_val <= 0:
                vix_val = 20
            w_eq = min(12.0 / vix_val, 1.0)
            # Equal weight among held sectors
            w_per_sector = w_eq / len(held)
            sector_return = sum(returns_df[s].iloc[i] * w_per_sector for s in held)
            port_returns.iloc[i] = sector_return + (1 - w_eq) * gld_ret.iloc[i]

        # TX costs when holdings change
        if set(held) != set(prev_sectors) and len(held) > 0:
            # Count number of position changes
            old_set = set(prev_sectors)
            new_set = set(held)
            trades = len(old_set.symmetric_difference(new_set))
            tx = trades * (tx_cost_bp / 10000)
            port_returns.iloc[i] -= tx

        prev_sectors = held

    return port_returns


def compute_metrics(ret_series, name="Strategy"):
    """Compute standard performance metrics."""
    r = ret_series.dropna()
    n = len(r)
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Win rate
    win_rate = (r > 0).mean()

    # Turnover proxy (days with returns)
    return {
        'name': name,
        'n_days': n,
        'ann_return': float(ann_ret),
        'ann_vol': float(ann_vol),
        'sharpe': float(sharpe),
        'mdd': float(mdd),
        'calmar': float(calmar),
        'sortino': float(sortino),
        'win_rate': float(win_rate),
    }


# ============================================================
# 5. Run All Strategy Variants
# ============================================================
print("\n" + "=" * 70)
print("[4] Running Strategy Variants")
print("=" * 70)

# Benchmark: SPY + GLD VT
bench_ret = compute_vt_benchmark(returns, vix)
bench_metrics = compute_metrics(bench_ret, "Benchmark (SPY+GLD VT)")
print(f"\n  Benchmark: Sharpe={bench_metrics['sharpe']:.3f}, "
      f"Ann Ret={bench_metrics['ann_return']:.3f}, MDD={bench_metrics['mdd']:.3f}")

strategies = {}

# (a) Weekly top-1 momentum, 60d lookback
print("\n  [a] Weekly Top-1, 60d lookback...")
ret_a = compute_sector_momentum_weekly(returns, vix, prices, fridays,
                                        lookback_days=60, top_n=1, hold_weeks=1, tx_cost_bp=5)
strategies['weekly_top1_60d'] = compute_metrics(ret_a, "Weekly Top-1 (60d)")
print(f"      Sharpe={strategies['weekly_top1_60d']['sharpe']:.3f}")

# (b) Weekly top-1 momentum, 20d lookback
print("  [b] Weekly Top-1, 20d lookback...")
ret_b = compute_sector_momentum_weekly(returns, vix, prices, fridays,
                                        lookback_days=20, top_n=1, hold_weeks=1, tx_cost_bp=5)
strategies['weekly_top1_20d'] = compute_metrics(ret_b, "Weekly Top-1 (20d)")
print(f"      Sharpe={strategies['weekly_top1_20d']['sharpe']:.3f}")

# (c) Weekly top-2 equal weight, 60d lookback
print("  [c] Weekly Top-2, 60d lookback...")
ret_c = compute_sector_momentum_weekly(returns, vix, prices, fridays,
                                        lookback_days=60, top_n=2, hold_weeks=1, tx_cost_bp=5)
strategies['weekly_top2_60d'] = compute_metrics(ret_c, "Weekly Top-2 (60d)")
print(f"      Sharpe={strategies['weekly_top2_60d']['sharpe']:.3f}")

# (d) Weekly top-1 with 2-week hold
print("  [d] Weekly Top-1, 60d lookback, 2-week hold...")
ret_d = compute_sector_momentum_weekly(returns, vix, prices, fridays,
                                        lookback_days=60, top_n=1, hold_weeks=2, tx_cost_bp=5)
strategies['weekly_top1_60d_2whold'] = compute_metrics(ret_d, "Weekly Top-1 (60d, 2wk hold)")
print(f"      Sharpe={strategies['weekly_top1_60d_2whold']['sharpe']:.3f}")

# (e) Bi-weekly rebalancing, top-1, 60d
print("  [e] Bi-weekly Top-1, 60d lookback...")
ret_e = compute_sector_momentum_weekly(returns, vix, prices, bi_weekly,
                                        lookback_days=60, top_n=1, hold_weeks=1, tx_cost_bp=5)
strategies['biweekly_top1_60d'] = compute_metrics(ret_e, "Bi-weekly Top-1 (60d)")
print(f"      Sharpe={strategies['biweekly_top1_60d']['sharpe']:.3f}")

# Also test with 0 TX cost to see turnover impact
print("\n  [f] Weekly Top-1, 60d, ZERO TX (to isolate turnover effect)...")
ret_f = compute_sector_momentum_weekly(returns, vix, prices, fridays,
                                        lookback_days=60, top_n=1, hold_weeks=1, tx_cost_bp=0)
strategies['weekly_top1_60d_notx'] = compute_metrics(ret_f, "Weekly Top-1 (60d, 0 TX)")
print(f"      Sharpe={strategies['weekly_top1_60d_notx']['sharpe']:.3f}")

# ============================================================
# 6. Summary Table
# ============================================================
print("\n" + "=" * 70)
print("[5] Full-Sample Summary")
print("=" * 70)
print(f"{'Strategy':<35} {'Sharpe':>7} {'AnnRet':>8} {'AnnVol':>8} {'MDD':>8} {'Calmar':>7} {'WinRate':>8}")
print("-" * 90)
print(f"{'Benchmark (SPY+GLD VT)':<35} {bench_metrics['sharpe']:>7.3f} {bench_metrics['ann_return']:>8.3f} "
      f"{bench_metrics['ann_vol']:>8.3f} {bench_metrics['mdd']:>8.3f} {bench_metrics['calmar']:>7.3f} {bench_metrics['win_rate']:>8.3f}")
for key, m in strategies.items():
    print(f"{m['name']:<35} {m['sharpe']:>7.3f} {m['ann_return']:>8.3f} "
          f"{m['ann_vol']:>8.3f} {m['mdd']:>8.3f} {m['calmar']:>7.3f} {m['win_rate']:>8.3f}")

# ============================================================
# 7. Cross-OOS Validation (5 periods)
# ============================================================
print("\n" + "=" * 70)
print("[6] Cross-OOS Validation (5 periods)")
print("=" * 70)

# Define 5 OOS periods (non-overlapping ~4 years each)
all_years = sorted(returns.index.year.unique())
n_years = len(all_years)
period_size = n_years // 5

oos_periods = []
for i in range(5):
    start_yr = all_years[i * period_size]
    end_yr = all_years[min((i + 1) * period_size - 1, n_years - 1)]
    if i == 4:
        end_yr = all_years[-1]
    oos_periods.append((start_yr, end_yr))

print(f"  OOS periods: {oos_periods}")

# Run each strategy variant on each OOS period
cross_oos_results = {}
strategy_returns = {
    'weekly_top1_60d': ret_a,
    'weekly_top1_20d': ret_b,
    'weekly_top2_60d': ret_c,
    'weekly_top1_60d_2whold': ret_d,
    'biweekly_top1_60d': ret_e,
}

for strat_name, strat_ret in strategy_returns.items():
    oos_sharpes = []
    oos_details = []
    for start_yr, end_yr in oos_periods:
        mask = (strat_ret.index.year >= start_yr) & (strat_ret.index.year <= end_yr)
        oos_ret = strat_ret[mask]
        bench_oos = bench_ret[mask]

        if len(oos_ret) < 100:
            continue

        oos_m = compute_metrics(oos_ret, f"OOS {start_yr}-{end_yr}")
        bench_oos_m = compute_metrics(bench_oos, f"Bench {start_yr}-{end_yr}")

        # DM test: excess returns vs benchmark
        excess = oos_ret - bench_oos
        excess = excess.dropna()
        if len(excess) > 50:
            t_stat, p_val = stats.ttest_1samp(excess, 0)
        else:
            t_stat, p_val = 0, 1

        oos_sharpes.append(oos_m['sharpe'])
        oos_details.append({
            'period': f"{start_yr}-{end_yr}",
            'n_days': oos_m['n_days'],
            'strat_sharpe': oos_m['sharpe'],
            'bench_sharpe': bench_oos_m['sharpe'],
            'excess_sharpe': oos_m['sharpe'] - bench_oos_m['sharpe'],
            'excess_t': float(t_stat),
            'excess_p': float(p_val),
            'strat_mdd': oos_m['mdd'],
            'bench_mdd': bench_oos_m['mdd'],
        })

    # Compute mean excess Sharpe and pooled t-stat
    excess_sharpes = [d['excess_sharpe'] for d in oos_details]
    if len(excess_sharpes) >= 3:
        mean_excess = np.mean(excess_sharpes)
        se_excess = np.std(excess_sharpes, ddof=1) / np.sqrt(len(excess_sharpes))
        pooled_t = mean_excess / se_excess if se_excess > 0 else 0
    else:
        mean_excess, pooled_t = 0, 0

    cross_oos_results[strat_name] = {
        'oos_details': oos_details,
        'mean_oos_sharpe': float(np.mean(oos_sharpes)) if oos_sharpes else 0,
        'std_oos_sharpe': float(np.std(oos_sharpes, ddof=1)) if len(oos_sharpes) > 1 else 0,
        'mean_excess_sharpe': float(mean_excess),
        'pooled_t': float(pooled_t),
        'harvey_pass': abs(pooled_t) > 3.0,
        'n_positive': sum(1 for s in excess_sharpes if s > 0),
        'n_periods': len(oos_details),
    }

# Print cross-OOS summary
print(f"\n{'Strategy':<35} {'Mean OOS':>9} {'Std OOS':>8} {'Mean Exc':>9} {'Pooled t':>9} {'Harvey':>7} {'Win':>5}")
print("-" * 90)
for strat_name, res in cross_oos_results.items():
    harv = "PASS" if res['harvey_pass'] else "FAIL"
    print(f"{strat_name:<35} {res['mean_oos_sharpe']:>9.3f} {res['std_oos_sharpe']:>8.3f} "
          f"{res['mean_excess_sharpe']:>9.3f} {res['pooled_t']:>9.3f} {harv:>7} "
          f"{res['n_positive']}/{res['n_periods']}")

# Print detailed OOS for best strategy
best_strat = max(cross_oos_results, key=lambda k: cross_oos_results[k]['pooled_t'])
print(f"\n  Best strategy: {best_strat}")
print(f"\n  Detailed OOS for {best_strat}:")
print(f"  {'Period':<15} {'Strat Sharpe':>12} {'Bench Sharpe':>12} {'Excess':>8} {'t-stat':>8} {'MDD(S)':>8} {'MDD(B)':>8}")
for d in cross_oos_results[best_strat]['oos_details']:
    print(f"  {d['period']:<15} {d['strat_sharpe']:>12.3f} {d['bench_sharpe']:>12.3f} "
          f"{d['excess_sharpe']:>8.3f} {d['excess_t']:>8.3f} {d['strat_mdd']:>8.3f} {d['bench_mdd']:>8.3f}")

# ============================================================
# 8. Full-Sample Harvey Test (all strategies vs benchmark)
# ============================================================
print("\n" + "=" * 70)
print("[7] Full-Sample Harvey Test (excess returns vs benchmark)")
print("=" * 70)

harvey_results = {}
for strat_name, strat_ret in strategy_returns.items():
    excess = (strat_ret - bench_ret).dropna()
    t_stat, p_val = stats.ttest_1samp(excess, 0)
    harvey_results[strat_name] = {
        'excess_mean_ann': float(excess.mean() * 252),
        't_stat': float(t_stat),
        'p_val': float(p_val),
        'harvey_pass': abs(float(t_stat)) > 3.0,
    }
    harv = "PASS" if harvey_results[strat_name]['harvey_pass'] else "FAIL"
    print(f"  {strat_name:<35} excess={harvey_results[strat_name]['excess_mean_ann']:>7.4f} "
          f"t={t_stat:>7.3f} p={p_val:>7.4f} Harvey: {harv}")

# ============================================================
# 9. Turnover Analysis
# ============================================================
print("\n" + "=" * 70)
print("[8] Turnover Analysis")
print("=" * 70)

def count_turnover(returns_df, vix_series, prices_df, rebal_dates,
                   lookback_days=60, top_n=1, hold_weeks=1):
    """Count number of sector switches."""
    sector_prices = prices_df[sector_etfs]
    sector_momentum = sector_prices.pct_change(lookback_days)

    prev_sectors = []
    switches = 0
    total_rebals = 0
    hold_counter = 0

    for date in rebal_dates:
        if date not in sector_momentum.index:
            continue
        if hold_counter > 0:
            hold_counter -= 1
            continue

        mom = sector_momentum.loc[date].dropna()
        if len(mom) >= top_n:
            new_sectors = mom.nlargest(top_n).index.tolist()
            total_rebals += 1
            if set(new_sectors) != set(prev_sectors):
                switches += 1
            prev_sectors = new_sectors
            hold_counter = hold_weeks - 1

    return switches, total_rebals

configs = [
    ('weekly_top1_60d', fridays, 60, 1, 1),
    ('weekly_top1_20d', fridays, 20, 1, 1),
    ('weekly_top2_60d', fridays, 60, 2, 1),
    ('weekly_top1_60d_2whold', fridays, 60, 1, 2),
    ('biweekly_top1_60d', bi_weekly, 60, 1, 1),
]

turnover_data = {}
for name, dates, lb, tn, hw in configs:
    switches, total = count_turnover(returns, vix, prices, dates, lb, tn, hw)
    switch_rate = switches / total if total > 0 else 0
    turnover_data[name] = {
        'total_rebals': total,
        'switches': switches,
        'switch_rate': float(switch_rate),
        'avg_trades_per_year': float(switches / (len(returns) / 252)),
    }
    print(f"  {name:<35} Rebals={total:>5}, Switches={switches:>5}, "
          f"Rate={switch_rate:.1%}, Trades/yr={turnover_data[name]['avg_trades_per_year']:.1f}")

# ============================================================
# 10. Sector Selection Frequency
# ============================================================
print("\n" + "=" * 70)
print("[9] Sector Selection Frequency (Weekly Top-1, 60d)")
print("=" * 70)

sector_prices = prices[sector_etfs]
sector_momentum_60d = sector_prices.pct_change(60)

sector_counts = {s: 0 for s in sector_etfs}
total_selections = 0
for date in fridays:
    if date not in sector_momentum_60d.index:
        continue
    mom = sector_momentum_60d.loc[date].dropna()
    if len(mom) > 0:
        top = mom.idxmax()
        sector_counts[top] += 1
        total_selections += 1

print(f"  Total selections: {total_selections}")
for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
    pct = count / total_selections * 100 if total_selections > 0 else 0
    print(f"  {sector}: {count:>4} ({pct:.1f}%)")

# ============================================================
# 11. Regime Analysis (VIX-based)
# ============================================================
print("\n" + "=" * 70)
print("[10] Regime Analysis")
print("=" * 70)

vix_prev = vix.shift(1)

# Regime definitions
regimes = {
    'Low VIX (<15)': vix_prev < 15,
    'Mid VIX (15-25)': (vix_prev >= 15) & (vix_prev < 25),
    'High VIX (25-35)': (vix_prev >= 25) & (vix_prev < 35),
    'Crisis VIX (>35)': vix_prev >= 35,
}

best_ret = strategy_returns[best_strat]

for regime_name, mask in regimes.items():
    valid = mask.reindex(best_ret.index).fillna(False)
    strat_r = best_ret[valid]
    bench_r = bench_ret[valid]

    if len(strat_r) < 50:
        print(f"  {regime_name}: Too few observations ({len(strat_r)})")
        continue

    sm = compute_metrics(strat_r, regime_name)
    bm = compute_metrics(bench_r, regime_name)

    excess = (strat_r - bench_r).dropna()
    if len(excess) > 20:
        t, p = stats.ttest_1samp(excess, 0)
    else:
        t, p = 0, 1

    print(f"  {regime_name:<25} Strat Sharpe={sm['sharpe']:>6.3f} Bench Sharpe={bm['sharpe']:>6.3f} "
          f"Excess t={t:>6.3f} n={len(strat_r)}")

# ============================================================
# 12. Rolling Sharpe Comparison
# ============================================================
print("\n" + "=" * 70)
print("[11] Rolling 1Y Sharpe Stability")
print("=" * 70)

window = 252
best_rolling = strategy_returns[best_strat].rolling(window).apply(
    lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
).dropna()
bench_rolling = bench_ret.rolling(window).apply(
    lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0
).dropna()

# Align
common = best_rolling.index.intersection(bench_rolling.index)
best_rolling = best_rolling.loc[common]
bench_rolling = bench_rolling.loc[common]

excess_rolling = best_rolling - bench_rolling
pct_outperform = (excess_rolling > 0).mean()

print(f"  Rolling 1Y Sharpe — {best_strat}:")
print(f"    Strategy mean: {best_rolling.mean():.3f}, std: {best_rolling.std():.3f}")
print(f"    Benchmark mean: {bench_rolling.mean():.3f}, std: {bench_rolling.std():.3f}")
print(f"    % windows outperform: {pct_outperform:.1%}")
print(f"    Excess Sharpe mean: {excess_rolling.mean():.3f}")

# ============================================================
# 13. Compile Results
# ============================================================
elapsed = time.time() - start_time

results = {
    'experiment_id': 'K563',
    'title': 'Weekly Sector Momentum VT',
    'timestamp': datetime.now().isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'data_source': 'yfinance',
    'period': f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    'n_days': len(returns),
    'tickers': list(tickers.keys()),
    'sector_etfs': sector_etfs,
    'literature': [
        'Jegadeesh & Titman (1993) JF',
        'Moskowitz & Grinblatt (1999) JF - Industry Momentum',
        'Moreira & Muir (2017) JF - Volatility-Managed Portfolios',
        'Barroso & Santa-Clara (2015) JFE',
        'Harvey Liu Zhu (2016) RFS',
        "O'Neal (2000) FAJ - Industry Momentum",
    ],
    'descriptive_stats': desc_stats,
    'benchmark': bench_metrics,
    'strategies': strategies,
    'cross_oos': cross_oos_results,
    'harvey_tests': harvey_results,
    'turnover': turnover_data,
    'sector_selection_frequency': {s: int(c) for s, c in sector_counts.items()},
    'regime_analysis': {},
    'rolling_sharpe': {
        'pct_windows_outperform': float(pct_outperform),
        'mean_excess_rolling_sharpe': float(excess_rolling.mean()),
    },
    'best_strategy': best_strat,
    'k562_comparison': {
        'k562_daily_sharpe': 2.157,
        'k562_monthly_sharpe': 1.228,
        'k563_best_weekly_sharpe': strategies[best_strat]['sharpe'],
        'benchmark_sharpe': bench_metrics['sharpe'],
    },
    'conclusion': '',
}

# Add regime analysis to results
for regime_name, mask in regimes.items():
    valid = mask.reindex(best_ret.index).fillna(False)
    strat_r = best_ret[valid]
    bench_r = bench_ret[valid]
    if len(strat_r) >= 50:
        sm = compute_metrics(strat_r, regime_name)
        bm = compute_metrics(bench_r, regime_name)
        results['regime_analysis'][regime_name] = {
            'strat_sharpe': sm['sharpe'],
            'bench_sharpe': bm['sharpe'],
            'n_days': len(strat_r),
        }

# Determine conclusion
any_harvey_pass = any(v['harvey_pass'] for v in harvey_results.values())
any_cross_oos_pass = any(v['harvey_pass'] for v in cross_oos_results.values())
best_sharpe = strategies[best_strat]['sharpe']
bench_sharpe = bench_metrics['sharpe']

if any_harvey_pass and any_cross_oos_pass:
    results['conclusion'] = (
        f"POSITIVE: Weekly sector momentum adds statistically significant alpha. "
        f"Best variant: {best_strat} (Sharpe {best_sharpe:.3f}) vs benchmark {bench_sharpe:.3f}. "
        f"Harvey PASS in both full-sample and cross-OOS."
    )
elif any_harvey_pass:
    results['conclusion'] = (
        f"MIXED: Full-sample Harvey PASS but cross-OOS FAIL. "
        f"Best: {best_strat} Sharpe {best_sharpe:.3f} vs benchmark {bench_sharpe:.3f}. "
        f"Alpha is inconsistent across time periods — likely data-mined."
    )
elif best_sharpe > bench_sharpe:
    results['conclusion'] = (
        f"NULL: Weekly sector momentum improves Sharpe numerically ({best_sharpe:.3f} vs {bench_sharpe:.3f}) "
        f"but does NOT pass Harvey t>3.0 in full-sample or cross-OOS. "
        f"No reliable alpha — improvement is within noise. "
        f"Weekly sits between K562's daily (2.157) and monthly (1.228) as expected."
    )
else:
    results['conclusion'] = (
        f"NULL: Weekly sector momentum (best Sharpe {best_sharpe:.3f}) "
        f"underperforms benchmark ({bench_sharpe:.3f}). No alpha at any frequency tested."
    )

print("\n" + "=" * 70)
print("[12] CONCLUSION")
print("=" * 70)
print(f"\n  {results['conclusion']}")
print(f"\n  Runtime: {elapsed:.1f}s")

# Save results
results_path = 'experiments/k563_weekly_sector_momentum_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")
