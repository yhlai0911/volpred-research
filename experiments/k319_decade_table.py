"""
K319: Decade-by-Decade Performance — The Complete Historical Record

Background: K288 tested cross-period stability on 4 periods. This creates the
DEFINITIVE decade-by-decade table for the website and papers.

Data: SPY, GLD, VIX daily from yfinance. Full available history.

Methodology:
  Split into decades:
    2005-2009 (includes GFC)
    2010-2014 (QE recovery)
    2015-2019 (low vol bull)
    2020-2024 (COVID + rate hike)
    2025-2026 (current, partial)

  4 strategies:
    1. SPY B&H
    2. 50/50 SPY/GLD B&H (monthly rebalance)
    3. 50/50 + VT (12/VIX formula)
    4. 50/50 + VT (Step Rule: VIX<12:100%, 12-15:80%, 15-20:60%, 20-25:50%, 25-35:40%, >35:30%)

  Metrics per decade: CAGR, Sharpe, MDD, worst month, best month

Data source: yfinance (SPY, GLD, ^VIX)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# 1. Download data
# ─────────────────────────────────────────────────────────────────────────────
print("=" * 80)
print("K319: Decade-by-Decade Performance — The Complete Historical Record")
print("=" * 80)
print(f"\nExperiment run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("Data source: yfinance (SPY, GLD, ^VIX)")

spy = yf.download("SPY", start="2004-11-01", end="2026-04-01", auto_adjust=True, progress=False)
gld = yf.download("GLD", start="2004-11-01", end="2026-04-01", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2004-11-01", end="2026-04-01", auto_adjust=True, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(gld.columns, pd.MultiIndex):
    gld.columns = gld.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Flatten index if needed
spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
gld.index = gld.index.tz_localize(None) if gld.index.tz else gld.index
vix.index = vix.index.tz_localize(None) if vix.index.tz else vix.index

# Align on common dates
common_dates = spy.index.intersection(gld.index).intersection(vix.index)
common_dates = common_dates.sort_values()

df = pd.DataFrame({
    'SPY': spy.loc[common_dates, 'Close'],
    'GLD': gld.loc[common_dates, 'Close'],
    'VIX': vix.loc[common_dates, 'Close'],
}, index=common_dates)
df = df.dropna()

print(f"\nData range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"Total trading days: {len(df)}")

# Daily returns
df['SPY_ret'] = df['SPY'].pct_change()
df['GLD_ret'] = df['GLD'].pct_change()

# ─────────────────────────────────────────────────────────────────────────────
# 2. Strategy definitions (monthly rebalancing)
# ─────────────────────────────────────────────────────────────────────────────

def vt_12_vix(vix_level):
    """12/VIX formula, capped at 1.0"""
    return min(12.0 / vix_level, 1.0)


def vt_step_rule(vix_level):
    """Step rule from K1157:
    VIX<12: 100%, 12-15: 80%, 15-20: 60%, 20-25: 50%, 25-35: 40%, >35: 30%
    """
    if vix_level < 12:
        return 1.0
    elif vix_level < 15:
        return 0.8
    elif vix_level < 20:
        return 0.6
    elif vix_level < 25:
        return 0.5
    elif vix_level < 35:
        return 0.4
    else:
        return 0.3


def compute_strategy_returns(data, strategy_name):
    """
    Compute daily returns for each strategy with monthly rebalancing.

    Strategies:
    1. SPY B&H: 100% SPY
    2. 50/50 B&H: 50% SPY + 50% GLD, monthly rebalance
    3. 50/50 + VT (12/VIX): VT-weighted 50/50, monthly rebalance
    4. 50/50 + VT (Step Rule): VT-weighted 50/50, monthly rebalance

    VT applied as: portfolio = w_equity * (spy_w * SPY + gld_w * GLD) + (1 - w_equity) * 0
    Where w_equity comes from VT signal, and we assume cash (0 return) for the non-invested portion.
    """

    daily_rets = []

    # Get month-end dates for rebalancing
    months = data.index.to_period('M').unique()

    for i, month in enumerate(months):
        month_data = data[data.index.to_period('M') == month]
        if len(month_data) == 0:
            continue

        # Get VIX at start of month (first trading day) for VT signal
        vix_start = month_data['VIX'].iloc[0]

        if strategy_name == 'SPY B&H':
            # 100% SPY
            month_rets = month_data['SPY_ret']
        elif strategy_name == '50/50 B&H':
            # 50% SPY + 50% GLD, rebalanced monthly
            month_rets = 0.5 * month_data['SPY_ret'] + 0.5 * month_data['GLD_ret']
        elif strategy_name == '50/50 + VT (12/VIX)':
            w = vt_12_vix(vix_start)
            month_rets = w * (0.5 * month_data['SPY_ret'] + 0.5 * month_data['GLD_ret'])
        elif strategy_name == '50/50 + VT (Step)':
            w = vt_step_rule(vix_start)
            month_rets = w * (0.5 * month_data['SPY_ret'] + 0.5 * month_data['GLD_ret'])
        else:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        daily_rets.append(month_rets)

    return pd.concat(daily_rets).dropna()


def compute_metrics(daily_returns, period_label):
    """
    Compute CAGR, Sharpe, MDD, worst month, best month from daily returns.
    """
    if len(daily_returns) < 20:
        return None

    # Cumulative return
    cum = (1 + daily_returns).cumprod()

    # CAGR
    n_years = len(daily_returns) / 252.0
    total_ret = cum.iloc[-1] / cum.iloc[0] - 1 if cum.iloc[0] != 0 else 0
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    # Sharpe (annualized, rf=0 for simplicity)
    sharpe = daily_returns.mean() / daily_returns.std() * np.sqrt(252) if daily_returns.std() > 0 else 0

    # MDD
    rolling_max = cum.cummax()
    drawdowns = cum / rolling_max - 1
    mdd = drawdowns.min()

    # Monthly returns for worst/best month
    monthly_rets = daily_returns.resample('ME').apply(lambda x: (1 + x).prod() - 1)
    worst_month = monthly_rets.min()
    best_month = monthly_rets.max()
    worst_month_date = monthly_rets.idxmin().strftime('%Y-%m') if not monthly_rets.empty else 'N/A'
    best_month_date = monthly_rets.idxmax().strftime('%Y-%m') if not monthly_rets.empty else 'N/A'

    # Annualized volatility
    ann_vol = daily_returns.std() * np.sqrt(252)

    return {
        'CAGR': cagr,
        'Sharpe': sharpe,
        'Ann_Vol': ann_vol,
        'MDD': mdd,
        'Worst_Month': worst_month,
        'Worst_Month_Date': worst_month_date,
        'Best_Month': best_month,
        'Best_Month_Date': best_month_date,
        'Total_Return': total_ret,
        'N_Days': len(daily_returns),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. Define decades and strategies
# ─────────────────────────────────────────────────────────────────────────────

decades = {
    '2005-2009\n(GFC)': ('2005-01-01', '2009-12-31'),
    '2010-2014\n(QE Recovery)': ('2010-01-01', '2014-12-31'),
    '2015-2019\n(Low-Vol Bull)': ('2015-01-01', '2019-12-31'),
    '2020-2024\n(COVID+Rates)': ('2020-01-01', '2024-12-31'),
    '2025-2026\n(Current)': ('2025-01-01', '2026-12-31'),
}

strategies = ['SPY B&H', '50/50 B&H', '50/50 + VT (12/VIX)', '50/50 + VT (Step)']

# ─────────────────────────────────────────────────────────────────────────────
# 4. Compute metrics for each decade x strategy
# ─────────────────────────────────────────────────────────────────────────────

results = {}

for decade_name, (start, end) in decades.items():
    decade_data = df[(df.index >= start) & (df.index <= end)].copy()
    if len(decade_data) < 20:
        print(f"\nSkipping {decade_name}: insufficient data ({len(decade_data)} days)")
        continue

    print(f"\n{'─' * 60}")
    print(f"Decade: {decade_name.replace(chr(10), ' ')}")
    print(f"  Data: {decade_data.index[0].strftime('%Y-%m-%d')} to {decade_data.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(decade_data)}")
    print(f"  VIX range: {decade_data['VIX'].min():.1f} - {decade_data['VIX'].max():.1f} (mean {decade_data['VIX'].mean():.1f})")

    results[decade_name] = {}

    for strat in strategies:
        rets = compute_strategy_returns(decade_data, strat)
        metrics = compute_metrics(rets, decade_name)
        if metrics:
            results[decade_name][strat] = metrics

# Also compute full-period metrics
print(f"\n{'─' * 60}")
print(f"Full Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
full_name = f"Full Period\n({df.index[0].year}-{df.index[-1].year})"
results[full_name] = {}
for strat in strategies:
    rets = compute_strategy_returns(df, strat)
    metrics = compute_metrics(rets, "Full")
    if metrics:
        results[full_name][strat] = metrics

# ─────────────────────────────────────────────────────────────────────────────
# 5. Display results
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("DEFINITIVE DECADE-BY-DECADE PERFORMANCE TABLE")
print("=" * 120)

# Print CAGR table
print("\n┌─────────────────────────────────────────────────────────────────────┐")
print("│                           CAGR (%)                                 │")
print("├─────────────────────────────────────────────────────────────────────┤")
header = f"{'Decade':<25}"
for strat in strategies:
    header += f" {strat:>16}"
header += f" {'Winner':>16}"
print(header)
print("─" * 110)

decade_winners_cagr = {}
for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    row = f"{decade_name.replace(chr(10), ' '):<25}"
    best_cagr = -999
    best_strat = ""
    for strat in strategies:
        if strat in results[decade_name]:
            cagr = results[decade_name][strat]['CAGR']
            row += f" {cagr*100:>15.1f}%"
            if cagr > best_cagr:
                best_cagr = cagr
                best_strat = strat
        else:
            row += f" {'N/A':>16}"
    row += f" {best_strat:>16}"
    decade_winners_cagr[decade_name] = best_strat
    print(row)

# Print Sharpe table
print("\n┌─────────────────────────────────────────────────────────────────────┐")
print("│                          Sharpe Ratio                              │")
print("├─────────────────────────────────────────────────────────────────────┤")
header = f"{'Decade':<25}"
for strat in strategies:
    header += f" {strat:>16}"
header += f" {'Winner':>16}"
print(header)
print("─" * 110)

decade_winners_sharpe = {}
for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    row = f"{decade_name.replace(chr(10), ' '):<25}"
    best_sharpe = -999
    best_strat = ""
    for strat in strategies:
        if strat in results[decade_name]:
            sharpe = results[decade_name][strat]['Sharpe']
            row += f" {sharpe:>16.3f}"
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_strat = strat
        else:
            row += f" {'N/A':>16}"
    row += f" {best_strat:>16}"
    decade_winners_sharpe[decade_name] = best_strat
    print(row)

# Print MDD table
print("\n┌─────────────────────────────────────────────────────────────────────┐")
print("│                       Maximum Drawdown (%)                         │")
print("├─────────────────────────────────────────────────────────────────────┤")
header = f"{'Decade':<25}"
for strat in strategies:
    header += f" {strat:>16}"
header += f" {'Winner':>16}"
print(header)
print("─" * 110)

decade_winners_mdd = {}
for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    row = f"{decade_name.replace(chr(10), ' '):<25}"
    best_mdd = -999  # least negative = best
    best_strat = ""
    for strat in strategies:
        if strat in results[decade_name]:
            mdd = results[decade_name][strat]['MDD']
            row += f" {mdd*100:>15.1f}%"
            if mdd > best_mdd:
                best_mdd = mdd
                best_strat = strat
        else:
            row += f" {'N/A':>16}"
    row += f" {best_strat:>16}"
    decade_winners_mdd[decade_name] = best_strat
    print(row)

# Print Worst Month table
print("\n┌─────────────────────────────────────────────────────────────────────┐")
print("│                        Worst Month (%)                             │")
print("├─────────────────────────────────────────────────────────────────────┤")
header = f"{'Decade':<25}"
for strat in strategies:
    header += f" {strat:>16}"
print(header)
print("─" * 95)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    row = f"{decade_name.replace(chr(10), ' '):<25}"
    for strat in strategies:
        if strat in results[decade_name]:
            wm = results[decade_name][strat]['Worst_Month']
            wm_date = results[decade_name][strat]['Worst_Month_Date']
            row += f" {wm*100:>7.1f}% ({wm_date})"
        else:
            row += f" {'N/A':>16}"
    print(row)

# Print Best Month table
print("\n┌─────────────────────────────────────────────────────────────────────┐")
print("│                         Best Month (%)                             │")
print("├─────────────────────────────────────────────────────────────────────┤")
header = f"{'Decade':<25}"
for strat in strategies:
    header += f" {strat:>16}"
print(header)
print("─" * 95)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    row = f"{decade_name.replace(chr(10), ' '):<25}"
    for strat in strategies:
        if strat in results[decade_name]:
            bm = results[decade_name][strat]['Best_Month']
            bm_date = results[decade_name][strat]['Best_Month_Date']
            row += f" {bm*100:>7.1f}% ({bm_date})"
        else:
            row += f" {'N/A':>16}"
    print(row)

# ─────────────────────────────────────────────────────────────────────────────
# 6. Comprehensive per-decade detail with all metrics
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("DETAILED PER-DECADE BREAKDOWN")
print("=" * 120)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    clean_name = decade_name.replace(chr(10), ' ')
    print(f"\n{'━' * 80}")
    print(f"  {clean_name}")
    print(f"{'━' * 80}")

    print(f"  {'Strategy':<28} {'CAGR':>8} {'Sharpe':>8} {'Vol':>8} {'MDD':>8} {'Worst Mo':>12} {'Best Mo':>12}")
    print(f"  {'─' * 76}")

    for strat in strategies:
        if strat in results[decade_name]:
            m = results[decade_name][strat]
            print(f"  {strat:<28} {m['CAGR']*100:>7.1f}% {m['Sharpe']:>8.3f} {m['Ann_Vol']*100:>7.1f}% {m['MDD']*100:>7.1f}% {m['Worst_Month']*100:>7.1f}% ({m['Worst_Month_Date']}) {m['Best_Month']*100:>7.1f}% ({m['Best_Month_Date']})")

# ─────────────────────────────────────────────────────────────────────────────
# 7. "All-weather" analysis
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("ALL-WEATHER ANALYSIS")
print("=" * 120)

actual_decades = [d for d in decades.keys() if d in results and 'Current' not in d]
n_decades = len(actual_decades)

print(f"\nComplete decades analyzed: {n_decades}")
print(f"Decades: {', '.join([d.replace(chr(10), ' ') for d in actual_decades])}")

# Which strategy wins each decade (by Sharpe)?
print(f"\n{'Criterion':<20} ", end="")
for d in actual_decades:
    print(f"{d.replace(chr(10), ' '):>25}", end="")
print()
print("─" * (20 + 25 * n_decades))

for criterion, winners_dict in [("Best CAGR", decade_winners_cagr),
                                  ("Best Sharpe", decade_winners_sharpe),
                                  ("Best MDD", decade_winners_mdd)]:
    row = f"{criterion:<20} "
    for d in actual_decades:
        if d in winners_dict:
            row += f"{winners_dict[d]:>25}"
        else:
            row += f"{'N/A':>25}"
    print(row)

# Count wins
print(f"\n{'Strategy Wins (Sharpe across ' + str(n_decades) + ' decades)':}")
print("─" * 60)
for strat in strategies:
    sharpe_wins = sum(1 for d in actual_decades if decade_winners_sharpe.get(d) == strat)
    cagr_wins = sum(1 for d in actual_decades if decade_winners_cagr.get(d) == strat)
    mdd_wins = sum(1 for d in actual_decades if decade_winners_mdd.get(d) == strat)
    print(f"  {strat:<28} Sharpe wins: {sharpe_wins}/{n_decades}  CAGR wins: {cagr_wins}/{n_decades}  MDD wins: {mdd_wins}/{n_decades}")

# All-weather test
print(f"\nAll-weather test (wins ALL {n_decades} decades by Sharpe):")
for strat in strategies:
    wins = sum(1 for d in actual_decades if decade_winners_sharpe.get(d) == strat)
    status = "YES" if wins == n_decades else "NO"
    print(f"  {strat:<28} → {status} ({wins}/{n_decades})")

# ─────────────────────────────────────────────────────────────────────────────
# 8. VT advantage analysis: when does VT help most?
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("VT ADVANTAGE ANALYSIS (vs 50/50 B&H baseline)")
print("=" * 120)

print(f"\n{'Decade':<25} {'VT 12/VIX Sharpe':>20} {'50/50 BH Sharpe':>20} {'Sharpe Delta':>15} {'VT Helps?':>12}")
print("─" * 95)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    clean_name = decade_name.replace(chr(10), ' ')
    if '50/50 B&H' in results[decade_name] and '50/50 + VT (12/VIX)' in results[decade_name]:
        bh_sharpe = results[decade_name]['50/50 B&H']['Sharpe']
        vt_sharpe = results[decade_name]['50/50 + VT (12/VIX)']['Sharpe']
        delta = vt_sharpe - bh_sharpe
        helps = "YES" if delta > 0 else "NO"
        print(f"  {clean_name:<23} {vt_sharpe:>20.3f} {bh_sharpe:>20.3f} {delta:>+14.3f} {helps:>12}")

print(f"\n{'Decade':<25} {'VT 12/VIX MDD':>20} {'50/50 BH MDD':>20} {'MDD Improve':>15} {'VT Helps?':>12}")
print("─" * 95)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    clean_name = decade_name.replace(chr(10), ' ')
    if '50/50 B&H' in results[decade_name] and '50/50 + VT (12/VIX)' in results[decade_name]:
        bh_mdd = results[decade_name]['50/50 B&H']['MDD']
        vt_mdd = results[decade_name]['50/50 + VT (12/VIX)']['MDD']
        improve = vt_mdd - bh_mdd  # less negative = better
        helps = "YES" if improve > 0 else "NO"
        print(f"  {clean_name:<23} {vt_mdd*100:>19.1f}% {bh_mdd*100:>19.1f}% {improve*100:>+13.1f}pp {helps:>12}")

# ─────────────────────────────────────────────────────────────────────────────
# 9. 12/VIX vs Step Rule comparison
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("12/VIX vs STEP RULE COMPARISON")
print("=" * 120)

print(f"\n{'Decade':<25} {'12/VIX Sharpe':>15} {'Step Sharpe':>15} {'Diff':>10} {'12/VIX MDD':>15} {'Step MDD':>15} {'Diff':>10}")
print("─" * 105)

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    clean_name = decade_name.replace(chr(10), ' ')
    if '50/50 + VT (12/VIX)' in results[decade_name] and '50/50 + VT (Step)' in results[decade_name]:
        vt12 = results[decade_name]['50/50 + VT (12/VIX)']
        step = results[decade_name]['50/50 + VT (Step)']
        s_diff = vt12['Sharpe'] - step['Sharpe']
        m_diff = (vt12['MDD'] - step['MDD']) * 100
        print(f"  {clean_name:<23} {vt12['Sharpe']:>15.3f} {step['Sharpe']:>15.3f} {s_diff:>+9.3f} {vt12['MDD']*100:>14.1f}% {step['MDD']*100:>14.1f}% {m_diff:>+8.1f}pp")

# ─────────────────────────────────────────────────────────────────────────────
# 10. Current decade (2025-2026) positioning
# ─────────────────────────────────────────────────────────────────────────────

current_key = [k for k in results.keys() if 'Current' in k]
if current_key:
    print("\n" + "=" * 120)
    print("CURRENT DECADE POSITIONING (2025-2026, partial)")
    print("=" * 120)

    ck = current_key[0]
    current_data = df[df.index >= '2025-01-01']

    print(f"\n  Period: {current_data.index[0].strftime('%Y-%m-%d')} to {current_data.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(current_data)}")
    print(f"  Current VIX: {current_data['VIX'].iloc[-1]:.1f}")
    print(f"  VIX range in 2025: {current_data['VIX'].min():.1f} - {current_data['VIX'].max():.1f}")

    current_vix = current_data['VIX'].iloc[-1]
    print(f"\n  Current 12/VIX signal: {vt_12_vix(current_vix):.1%} equity exposure")
    print(f"  Current Step Rule signal: {vt_step_rule(current_vix):.0%} equity exposure")

    print(f"\n  {'Strategy':<28} {'YTD Return':>12} {'Sharpe':>8} {'MDD':>8}")
    print(f"  {'─' * 56}")
    for strat in strategies:
        if strat in results[ck]:
            m = results[ck][strat]
            print(f"  {strat:<28} {m['Total_Return']*100:>11.1f}% {m['Sharpe']:>8.3f} {m['MDD']*100:>7.1f}%")

# ─────────────────────────────────────────────────────────────────────────────
# 11. Summary & conclusions
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "=" * 120)
print("KEY FINDINGS")
print("=" * 120)

# Count how many decades each strategy wins
print("\n1. Sharpe winners by decade:")
for strat in strategies:
    wins = [d.replace(chr(10), ' ') for d in actual_decades if decade_winners_sharpe.get(d) == strat]
    if wins:
        print(f"   {strat}: {len(wins)}/{n_decades} — {', '.join(wins)}")

print("\n2. MDD winners by decade:")
for strat in strategies:
    wins = [d.replace(chr(10), ' ') for d in actual_decades if decade_winners_mdd.get(d) == strat]
    if wins:
        print(f"   {strat}: {len(wins)}/{n_decades} — {', '.join(wins)}")

# Consistency check: is VT always better than B&H in Sharpe?
vt_always_better_sharpe = True
vt_always_better_mdd = True
for d in actual_decades:
    if d in results:
        if '50/50 B&H' in results[d] and '50/50 + VT (12/VIX)' in results[d]:
            if results[d]['50/50 + VT (12/VIX)']['Sharpe'] <= results[d]['50/50 B&H']['Sharpe']:
                vt_always_better_sharpe = False
            if results[d]['50/50 + VT (12/VIX)']['MDD'] <= results[d]['50/50 B&H']['MDD']:
                vt_always_better_mdd = False

print(f"\n3. VT (12/VIX) always beats 50/50 B&H in Sharpe across all decades? {'YES' if vt_always_better_sharpe else 'NO'}")
print(f"   VT (12/VIX) always beats 50/50 B&H in MDD across all decades? {'YES' if vt_always_better_mdd else 'NO'}")

# Average improvement
avg_sharpe_improve = []
avg_mdd_improve = []
for d in actual_decades:
    if d in results and '50/50 B&H' in results[d] and '50/50 + VT (12/VIX)' in results[d]:
        avg_sharpe_improve.append(results[d]['50/50 + VT (12/VIX)']['Sharpe'] - results[d]['50/50 B&H']['Sharpe'])
        avg_mdd_improve.append((results[d]['50/50 + VT (12/VIX)']['MDD'] - results[d]['50/50 B&H']['MDD']) * 100)

if avg_sharpe_improve:
    print(f"\n4. Average VT Sharpe improvement over 50/50 B&H: {np.mean(avg_sharpe_improve):+.3f}")
    print(f"   Average VT MDD improvement over 50/50 B&H: {np.mean(avg_mdd_improve):+.1f}pp")
    print(f"   Sharpe improvement range: {min(avg_sharpe_improve):+.3f} to {max(avg_sharpe_improve):+.3f}")

# 12/VIX vs Step comparison
print(f"\n5. 12/VIX vs Step Rule:")
diff_12_step = []
for d in actual_decades:
    if d in results and '50/50 + VT (12/VIX)' in results[d] and '50/50 + VT (Step)' in results[d]:
        diff_12_step.append(results[d]['50/50 + VT (12/VIX)']['Sharpe'] - results[d]['50/50 + VT (Step)']['Sharpe'])
if diff_12_step:
    print(f"   Sharpe diff (12/VIX - Step): {np.mean(diff_12_step):+.3f} avg, range [{min(diff_12_step):+.3f}, {max(diff_12_step):+.3f}]")
    print(f"   {'12/VIX marginally better but Step is close enough for zero-math implementation' if np.mean(diff_12_step) > 0 else 'Step Rule comparable or better'}")

# ─────────────────────────────────────────────────────────────────────────────
# 12. Save results to JSON
# ─────────────────────────────────────────────────────────────────────────────

output = {
    'experiment': 'K319',
    'title': 'Decade-by-Decade Performance — The Complete Historical Record',
    'run_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance (SPY, GLD, ^VIX)',
    'data_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'total_trading_days': len(df),
    'strategies': strategies,
    'decades': {},
    'all_weather_test': {},
    'findings': {},
}

for decade_name in list(decades.keys()) + [full_name]:
    if decade_name not in results:
        continue
    clean_name = decade_name.replace(chr(10), ' ')
    output['decades'][clean_name] = {}
    for strat in strategies:
        if strat in results[decade_name]:
            m = results[decade_name][strat]
            output['decades'][clean_name][strat] = {
                'CAGR': round(m['CAGR'] * 100, 2),
                'Sharpe': round(m['Sharpe'], 3),
                'Ann_Vol': round(m['Ann_Vol'] * 100, 2),
                'MDD': round(m['MDD'] * 100, 2),
                'Worst_Month': round(m['Worst_Month'] * 100, 2),
                'Worst_Month_Date': m['Worst_Month_Date'],
                'Best_Month': round(m['Best_Month'] * 100, 2),
                'Best_Month_Date': m['Best_Month_Date'],
                'Total_Return': round(m['Total_Return'] * 100, 2),
            }

# All-weather
for strat in strategies:
    wins = sum(1 for d in actual_decades if decade_winners_sharpe.get(d) == strat)
    output['all_weather_test'][strat] = {
        'sharpe_wins': wins,
        'total_decades': n_decades,
        'is_all_weather': wins == n_decades,
    }

output['findings'] = {
    'vt_always_beats_bh_sharpe': vt_always_better_sharpe,
    'vt_always_beats_bh_mdd': vt_always_better_mdd,
    'avg_sharpe_improvement': round(np.mean(avg_sharpe_improve), 3) if avg_sharpe_improve else None,
    'avg_mdd_improvement_pp': round(np.mean(avg_mdd_improve), 1) if avg_mdd_improve else None,
    'formula_vs_step_sharpe_diff': round(np.mean(diff_12_step), 3) if diff_12_step else None,
}

results_path = 'experiments/k319_decade_results.json'
with open(results_path, 'w') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\nResults saved to {results_path}")

print("\n" + "=" * 80)
print("K319 COMPLETE")
print("=" * 80)
