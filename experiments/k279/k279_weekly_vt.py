"""
K279: Weekly VT — Can More Frequent Rebalancing Reduce Whipsaw Cost?
=====================================================================
[提出: 用戶, 執行: Claude]

Background:
  K278 showed monthly VT loses ~5.5%/yr to whipsaw (daily VT Sharpe 1.77 vs monthly 0.77).
  K220 showed daily TX cost destroys value at 5bps.
  Can WEEKLY rebalancing be the sweet spot?

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.

Methodology:
  1. Compare rebalance frequencies for 50/50+VT (12/VIX):
     - Daily, Weekly (Friday), Bi-weekly, Monthly
  2. TX costs: 0, 2, 5, 10 bps
  3. For each: Sharpe, MDD, turnover, net Sharpe
  4. Find OPTIMAL frequency at each TX cost level
  5. Weekly variants:
     - Fixed Friday rebalance
     - Conditional: only rebalance if weight change > 5%
     - Trigger: rebalance whenever VIX crosses regime boundary (15, 20, 25, 30)
  6. 5-period cross-OOS validation
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
RF_DAILY = 0.04 / 252
RF_ANNUAL = 0.04
VIX_THRESHOLD = 12.0  # 12/VIX rule
MAX_WEIGHT = 1.5
DATA_START = "2004-01-01"
DATA_END = "2025-01-01"  # 2005-2024 for analysis (need lookback for VIX)

COST_LEVELS_BPS = [0, 2, 5, 10]

# Cross-OOS periods (5 periods, ~4 years each)
OOS_PERIODS = [
    ("2005-01-03", "2008-12-31"),  # Period 1: pre-crisis + GFC
    ("2009-01-02", "2012-12-31"),  # Period 2: recovery
    ("2013-01-02", "2016-12-31"),  # Period 3: low-vol bull
    ("2017-01-03", "2020-12-31"),  # Period 4: vol spike + COVID
    ("2021-01-04", "2024-12-31"),  # Period 5: post-COVID
]

print("=" * 80)
print("K279: Weekly VT — Optimal Rebalancing Frequency for 50/50 SPY/GLD 12/VIX")
print("=" * 80)

# ==================================================================
# 1. Download data
# ==================================================================
print("\n[1/6] Downloading SPY, GLD, and VIX data...")

spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data["gld_ret"] = np.log(data["gld_close"] / data["gld_close"].shift(1))
data = data.dropna()

# 50/50 portfolio return (equal-weight SPY+GLD, before VT)
data["port_ret_unscaled"] = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

# 12/VIX weight (capped at MAX_WEIGHT)
data["vt_weight"] = (VIX_THRESHOLD / data["vix_close"]).clip(0, MAX_WEIGHT)

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  GLD starts: {gld_raw.index[0].date()}")

# ==================================================================
# 2. Define rebalancing schedules
# ==================================================================
print("\n[2/6] Setting up rebalancing schedules...")

# Daily: every day
data["rebal_daily"] = True

# Weekly: every Friday (weekday == 4)
data["rebal_weekly_fri"] = data.index.weekday == 4

# Bi-weekly: every other Friday
fridays = data.index[data.index.weekday == 4]
biweekly_fridays = fridays[::2]  # every other Friday
data["rebal_biweekly"] = data.index.isin(biweekly_fridays)

# Monthly: first trading day of each month
data["month_key"] = data.index.to_period("M")
first_days = data.groupby("month_key").head(1).index
data["rebal_monthly"] = data.index.isin(first_days)

# VIX trigger: rebalance whenever VIX crosses regime boundary
vix_boundaries = [15, 20, 25, 30]
data["vix_regime"] = pd.cut(data["vix_close"], bins=[0] + vix_boundaries + [200], labels=False)
data["regime_change"] = data["vix_regime"] != data["vix_regime"].shift(1)
# Also rebalance on first day
data.loc[data.index[0], "regime_change"] = True
data["rebal_vix_trigger"] = data["regime_change"]

# Conditional weekly: only rebalance on Friday if weight change > 5%
# (Need to compute in the strategy function since we need to know current weight)

# Count rebalance days in full sample
for col_name, col_label in [
    ("rebal_daily", "Daily"),
    ("rebal_weekly_fri", "Weekly (Fri)"),
    ("rebal_biweekly", "Bi-weekly"),
    ("rebal_monthly", "Monthly"),
    ("rebal_vix_trigger", "VIX Trigger"),
]:
    count = data[col_name].sum()
    per_year = count / (len(data) / 252)
    print(f"  {col_label:<20}: {count:>5} days ({per_year:.0f}/yr)")


# ==================================================================
# 3. Strategy runner
# ==================================================================
def run_vt_strategy(df, rebal_col, cost_bps, strategy_name,
                    conditional_threshold=None):
    """
    Run 50/50 SPY/GLD with 12/VIX VT at given rebalancing schedule.

    Args:
        df: DataFrame with port_ret_unscaled and vt_weight
        rebal_col: column name for rebalancing dates (boolean)
        cost_bps: transaction cost in bps per unit of weight change
        strategy_name: label
        conditional_threshold: if not None, only rebalance if
                              abs(new_weight - current_weight) > threshold

    Returns: dict with performance metrics
    """
    n = len(df)
    weights = np.zeros(n)
    port_returns = np.zeros(n)
    n_rebalances = 0
    total_weight_turnover = 0.0
    total_tx_cost = 0.0

    # Initialize
    current_w = df["vt_weight"].iloc[0]
    weights[0] = current_w
    port_returns[0] = current_w * df["port_ret_unscaled"].iloc[0]

    for t in range(1, n):
        new_w_signal = df["vt_weight"].iloc[t]
        is_rebal_day = df[rebal_col].iloc[t]

        # Decide whether to rebalance
        do_rebalance = False
        if is_rebal_day:
            if conditional_threshold is not None:
                # Only rebalance if change is large enough
                if abs(new_w_signal - current_w) > conditional_threshold:
                    do_rebalance = True
            else:
                do_rebalance = True

        if do_rebalance:
            weight_change = abs(new_w_signal - current_w)
            if weight_change > 0.0001:
                n_rebalances += 1
                total_weight_turnover += weight_change
                tx_cost = weight_change * cost_bps / 10000
                total_tx_cost += tx_cost
            else:
                tx_cost = 0.0
            current_w = new_w_signal
        else:
            tx_cost = 0.0

        weights[t] = current_w
        port_returns[t] = current_w * df["port_ret_unscaled"].iloc[t] - tx_cost

    # Compute metrics
    cum_ret = np.exp(np.cumsum(port_returns))
    total_years = n / 252

    ann_ret = (cum_ret[-1] ** (1 / total_years)) - 1
    ann_vol = np.std(port_returns) * np.sqrt(252)
    sharpe = (np.mean(port_returns) - RF_DAILY) / np.std(port_returns) * np.sqrt(252)

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns)

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    # Sortino
    downside = port_returns[port_returns < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Monthly win rate
    monthly_rets = pd.Series(port_returns, index=df.index).resample("ME").sum()
    win_rate = (monthly_rets > 0).mean()

    # Annual turnover
    ann_turnover = total_weight_turnover / total_years

    # Annual TX cost
    ann_tx_cost = total_tx_cost / total_years

    return {
        "strategy": strategy_name,
        "cost_bps": cost_bps,
        "sharpe": sharpe,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "ann_turnover": ann_turnover,
        "n_rebalances": n_rebalances,
        "rebalances_per_year": n_rebalances / total_years,
        "win_rate_monthly": win_rate,
        "avg_weight": np.mean(weights),
        "total_growth": cum_ret[-1],
        "total_years": total_years,
        "ann_tx_cost": ann_tx_cost,
        "cum_returns": cum_ret,
        "port_returns": port_returns,
        "weights": weights,
    }


# ==================================================================
# 4. Run all frequency + cost combinations (full sample)
# ==================================================================
print("\n[3/6] Running full-sample analysis (all frequencies x all TX costs)...")

# Strategy definitions: (rebal_col, label, conditional_threshold)
strategy_defs = [
    ("rebal_daily", "Daily", None),
    ("rebal_weekly_fri", "Weekly (Fri)", None),
    ("rebal_weekly_fri", "Weekly Conditional (>5%)", 0.05),
    ("rebal_biweekly", "Bi-weekly", None),
    ("rebal_monthly", "Monthly", None),
    ("rebal_vix_trigger", "VIX Trigger", None),
]

# Run all combinations
full_results = {}
for rebal_col, strat_name, cond_thresh in strategy_defs:
    full_results[strat_name] = {}
    for cost_bps in COST_LEVELS_BPS:
        r = run_vt_strategy(data, rebal_col, cost_bps, strat_name,
                           conditional_threshold=cond_thresh)
        full_results[strat_name][cost_bps] = r
        if cost_bps == 0:
            print(f"  {strat_name:<30} 0bps: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
                  f"Turnover={r['ann_turnover']:.0f}x, Rebal/yr={r['rebalances_per_year']:.0f}")

# Buy & Hold 50/50 benchmark (no VT)
bh_returns = data["port_ret_unscaled"].values
bh_cum = np.exp(np.cumsum(bh_returns))
bh_years = len(data) / 252
bh_ann_ret = (bh_cum[-1] ** (1 / bh_years)) - 1
bh_ann_vol = np.std(bh_returns) * np.sqrt(252)
bh_sharpe = (np.mean(bh_returns) - RF_DAILY) / np.std(bh_returns) * np.sqrt(252)
bh_running_max = np.maximum.accumulate(bh_cum)
bh_dd = bh_cum / bh_running_max - 1
bh_max_dd = np.min(bh_dd)

print(f"\n  Buy & Hold 50/50:  Sharpe={bh_sharpe:.3f}, MDD={bh_max_dd:.1%}")

# ==================================================================
# 5. Main comparison table
# ==================================================================
print("\n[4/6] Results Summary — Full Sample")
print("=" * 80)

# Table 1: All strategies at 0 bps
print("\n--- Table 1: Strategy Comparison at 0 bps TX cost ---")
header = f"{'策略':<32} {'Sharpe':>7} {'Return':>8} {'Vol':>7} {'MDD':>8} {'Turnover':>9} {'Rebal/yr':>9}"
print(header)
print("-" * 82)

strat_names = [s[1] for s in strategy_defs]

for strat_name in strat_names:
    r = full_results[strat_name][0]
    print(f"{strat_name:<32} {r['sharpe']:>7.3f} {r['ann_return']:>7.2%} "
          f"{r['ann_vol']:>6.2%} {r['max_dd']:>7.2%} {r['ann_turnover']:>8.1f}x "
          f"{r['rebalances_per_year']:>8.0f}")

print(f"{'Buy & Hold 50/50':<32} {bh_sharpe:>7.3f} {bh_ann_ret:>7.2%} "
      f"{bh_ann_vol:>6.2%} {bh_max_dd:>7.2%} {'0.0x':>9} {'0':>9}")

# Table 2: Net Sharpe at different TX cost levels
print("\n--- Table 2: Net Sharpe at Different TX Cost Levels ---")
header2 = f"{'策略':<32}"
for cost in COST_LEVELS_BPS:
    header2 += f" {cost}bps".rjust(8)
header2 += "  Optimal"
print(header2)
print("-" * 82)

for strat_name in strat_names:
    row = f"{strat_name:<32}"
    sharpes = []
    for cost in COST_LEVELS_BPS:
        r = full_results[strat_name][cost]
        row += f" {r['sharpe']:>7.3f}"
        sharpes.append((cost, r['sharpe']))
    best_cost, best_sharpe = max(sharpes, key=lambda x: x[1])
    row += f"  @{best_cost}bps"
    print(row)

# Table 3: Find OPTIMAL frequency at each cost level
print("\n--- Table 3: Optimal Frequency at Each TX Cost Level ---")
for cost in COST_LEVELS_BPS:
    best_strat = None
    best_sharpe = -np.inf
    for strat_name in strat_names:
        s = full_results[strat_name][cost]["sharpe"]
        if s > best_sharpe:
            best_sharpe = s
            best_strat = strat_name
    print(f"  At {cost:>2} bps: {best_strat:<30} Sharpe={best_sharpe:.3f}")

# Table 4: TX cost impact per strategy
print("\n--- Table 4: TX Cost Impact (Sharpe degradation from 0bps) ---")
header4 = f"{'策略':<32} {'0bps':>8} {'2bps':>8} {'5bps':>8} {'10bps':>8} {'Degrad@5':>10}"
print(header4)
print("-" * 82)

for strat_name in strat_names:
    base = full_results[strat_name][0]["sharpe"]
    s2 = full_results[strat_name][2]["sharpe"]
    s5 = full_results[strat_name][5]["sharpe"]
    s10 = full_results[strat_name][10]["sharpe"]
    degrad5 = (s5 - base) / base * 100 if base != 0 else 0
    print(f"{strat_name:<32} {base:>7.3f} {s2:>7.3f} {s5:>7.3f} {s10:>7.3f} {degrad5:>9.1f}%")

# ==================================================================
# 6. Cross-OOS Validation (5 periods)
# ==================================================================
print("\n\n[5/6] Cross-OOS Validation (5 periods)...")
print("=" * 80)

# For each OOS period, run each strategy at 0bps and 5bps
oos_results = {}
for period_idx, (start, end) in enumerate(OOS_PERIODS):
    period_name = f"P{period_idx+1} ({start[:4]}-{end[:4]})"
    oos_data = data[(data.index >= start) & (data.index <= end)]

    if len(oos_data) < 50:
        print(f"  {period_name}: Skipped (only {len(oos_data)} days)")
        continue

    print(f"\n  {period_name}: {len(oos_data)} days")
    oos_results[period_name] = {}

    for rebal_col, strat_name, cond_thresh in strategy_defs:
        oos_results[period_name][strat_name] = {}
        for cost_bps in [0, 5]:
            r = run_vt_strategy(oos_data, rebal_col, cost_bps, strat_name,
                               conditional_threshold=cond_thresh)
            oos_results[period_name][strat_name][cost_bps] = r

# Cross-OOS Sharpe table at 0bps
print("\n--- Cross-OOS: Sharpe at 0bps ---")
header_oos = f"{'策略':<32}"
for pname in oos_results:
    short = pname.split("(")[1].split(")")[0]
    header_oos += f" {short:>12}"
header_oos += "  Mean".rjust(8) + "  Std".rjust(7) + "  Win%".rjust(7)
print(header_oos)
print("-" * 110)

for strat_name in strat_names:
    row = f"{strat_name:<32}"
    sharpes_list = []
    for pname in oos_results:
        s = oos_results[pname][strat_name][0]["sharpe"]
        row += f" {s:>12.3f}"
        sharpes_list.append(s)
    mean_s = np.mean(sharpes_list)
    std_s = np.std(sharpes_list)
    win_pct = np.mean([s > 0 for s in sharpes_list]) * 100
    row += f" {mean_s:>7.3f} {std_s:>6.3f} {win_pct:>5.0f}%"
    print(row)

# Cross-OOS Net Sharpe at 5bps
print("\n--- Cross-OOS: Net Sharpe at 5bps ---")
header_oos5 = f"{'策略':<32}"
for pname in oos_results:
    short = pname.split("(")[1].split(")")[0]
    header_oos5 += f" {short:>12}"
header_oos5 += "  Mean".rjust(8) + "  Std".rjust(7) + "  Win%".rjust(7)
print(header_oos5)
print("-" * 110)

for strat_name in strat_names:
    row = f"{strat_name:<32}"
    sharpes_list = []
    for pname in oos_results:
        s = oos_results[pname][strat_name][5]["sharpe"]
        row += f" {s:>12.3f}"
        sharpes_list.append(s)
    mean_s = np.mean(sharpes_list)
    std_s = np.std(sharpes_list)
    win_pct = np.mean([s > 0 for s in sharpes_list]) * 100
    row += f" {mean_s:>7.3f} {std_s:>6.3f} {win_pct:>5.0f}%"
    print(row)

# Cross-OOS MDD at 0bps
print("\n--- Cross-OOS: MDD at 0bps ---")
header_mdd = f"{'策略':<32}"
for pname in oos_results:
    short = pname.split("(")[1].split(")")[0]
    header_mdd += f" {short:>12}"
header_mdd += "  Mean".rjust(8) + "  Best%".rjust(8)
print(header_mdd)
print("-" * 110)

for strat_name in strat_names:
    row = f"{strat_name:<32}"
    mdds = []
    for pname in oos_results:
        m = oos_results[pname][strat_name][0]["max_dd"]
        row += f" {m:>11.2%}"
        mdds.append(m)
    mean_m = np.mean(mdds)
    # "Best" = shallowest MDD (least negative)
    row += f" {mean_m:>7.2%}"
    # How many periods is this the best strategy?
    print(row)

# ==================================================================
# 7. Detailed weekly variant comparison
# ==================================================================
print("\n\n[6/6] Weekly Variant Deep Dive")
print("=" * 80)

weekly_strats = ["Weekly (Fri)", "Weekly Conditional (>5%)", "VIX Trigger"]
print("\n--- Weekly Variants: Full Sample ---")
header_wk = f"{'Variant':<32} {'0bps':>8} {'2bps':>8} {'5bps':>8} {'10bps':>8} {'MDD':>8} {'Rebal/yr':>9} {'Turnover':>9}"
print(header_wk)
print("-" * 95)

for strat_name in weekly_strats:
    s0 = full_results[strat_name][0]
    s2 = full_results[strat_name][2]
    s5 = full_results[strat_name][5]
    s10 = full_results[strat_name][10]
    print(f"{strat_name:<32} {s0['sharpe']:>7.3f} {s2['sharpe']:>7.3f} "
          f"{s5['sharpe']:>7.3f} {s10['sharpe']:>7.3f} {s0['max_dd']:>7.2%} "
          f"{s0['rebalances_per_year']:>8.0f} {s0['ann_turnover']:>8.1f}x")

# Weekly Conditional with different thresholds
print("\n--- Conditional Weekly: Threshold Sensitivity ---")
cond_thresholds = [0.02, 0.05, 0.10, 0.15, 0.20]
header_ct = f"{'Threshold':<15} {'0bps':>8} {'5bps':>8} {'MDD':>8} {'Rebal/yr':>9} {'Turnover':>9}"
print(header_ct)
print("-" * 60)

for thresh in cond_thresholds:
    r0 = run_vt_strategy(data, "rebal_weekly_fri", 0, f"Cond {thresh:.0%}",
                         conditional_threshold=thresh)
    r5 = run_vt_strategy(data, "rebal_weekly_fri", 5, f"Cond {thresh:.0%}",
                         conditional_threshold=thresh)
    print(f"  > {thresh:.0%}{'':<10} {r0['sharpe']:>7.3f} {r5['sharpe']:>7.3f} "
          f"{r0['max_dd']:>7.2%} {r0['rebalances_per_year']:>8.0f} {r0['ann_turnover']:>8.1f}x")

# ==================================================================
# 8. Summary & Conclusion
# ==================================================================
print("\n\n" + "=" * 80)
print("K279 SUMMARY & CONCLUSIONS")
print("=" * 80)

# Find optimal strategy at each cost level
print("\n1. OPTIMAL FREQUENCY BY TX COST LEVEL:")
for cost in COST_LEVELS_BPS:
    best_strat = None
    best_sharpe = -np.inf
    for strat_name in strat_names:
        s = full_results[strat_name][cost]["sharpe"]
        if s > best_sharpe:
            best_sharpe = s
            best_strat = strat_name
    r = full_results[best_strat][cost]
    print(f"   @{cost:>2}bps: {best_strat:<30} Sharpe={best_sharpe:.3f} MDD={r['max_dd']:.1%}")

# Cross-OOS consistency
print("\n2. CROSS-OOS CONSISTENCY (mean Sharpe across 5 periods):")
for cost in [0, 5]:
    print(f"   At {cost}bps:")
    strat_means = []
    for strat_name in strat_names:
        sharpes_list = [oos_results[p][strat_name][cost]["sharpe"] for p in oos_results]
        m = np.mean(sharpes_list)
        strat_means.append((strat_name, m, np.std(sharpes_list)))
    strat_means.sort(key=lambda x: x[1], reverse=True)
    for sn, m, sd in strat_means:
        print(f"     {sn:<30} mean={m:.3f} std={sd:.3f}")

# Whipsaw vs TX cost tradeoff
print("\n3. WHIPSAW vs TX COST TRADEOFF (full sample):")
daily_0 = full_results["Daily"][0]["sharpe"]
daily_5 = full_results["Daily"][5]["sharpe"]
weekly_0 = full_results["Weekly (Fri)"][0]["sharpe"]
weekly_5 = full_results["Weekly (Fri)"][5]["sharpe"]
monthly_0 = full_results["Monthly"][0]["sharpe"]
monthly_5 = full_results["Monthly"][5]["sharpe"]

print(f"   Daily    : 0bps={daily_0:.3f}, 5bps={daily_5:.3f}, degrad={daily_0-daily_5:.3f}")
print(f"   Weekly   : 0bps={weekly_0:.3f}, 5bps={weekly_5:.3f}, degrad={weekly_0-weekly_5:.3f}")
print(f"   Monthly  : 0bps={monthly_0:.3f}, 5bps={monthly_5:.3f}, degrad={monthly_0-monthly_5:.3f}")
print(f"   Monthly→Weekly gain @0bps: {weekly_0-monthly_0:+.3f}")
print(f"   Weekly→Daily  gain @0bps: {daily_0-weekly_0:+.3f}")
print(f"   Monthly→Weekly gain @5bps: {weekly_5-monthly_5:+.3f}")
print(f"   Weekly→Daily  gain @5bps: {daily_5-weekly_5:+.3f}")

# Annual turnover comparison
print("\n4. ANNUAL TURNOVER COMPARISON:")
for strat_name in strat_names:
    r = full_results[strat_name][0]
    print(f"   {strat_name:<30} {r['ann_turnover']:.1f}x ({r['rebalances_per_year']:.0f} rebal/yr)")

# ==================================================================
# 9. Save results
# ==================================================================
print("\n\nSaving results...")

output = {
    "experiment": "K279_weekly_vt_optimal_rebalancing",
    "date": datetime.now().isoformat(),
    "config": {
        "asset_allocation": "50/50 SPY/GLD",
        "vt_rule": "12/VIX",
        "max_weight": MAX_WEIGHT,
        "data_start": str(data.index[0].date()),
        "data_end": str(data.index[-1].date()),
        "total_days": len(data),
        "total_years": round(len(data)/252, 1),
        "cost_levels_bps": COST_LEVELS_BPS,
        "oos_periods": OOS_PERIODS,
    },
    "buy_and_hold": {
        "sharpe": round(bh_sharpe, 4),
        "ann_return": round(bh_ann_ret, 4),
        "max_dd": round(bh_max_dd, 4),
    },
    "full_sample_results": {},
    "cross_oos_results": {},
}

# Full sample
for strat_name in strat_names:
    output["full_sample_results"][strat_name] = {}
    for cost in COST_LEVELS_BPS:
        r = full_results[strat_name][cost]
        output["full_sample_results"][strat_name][str(cost)] = {
            "sharpe": round(r["sharpe"], 4),
            "ann_return": round(r["ann_return"], 4),
            "ann_vol": round(r["ann_vol"], 4),
            "max_dd": round(r["max_dd"], 4),
            "calmar": round(r["calmar"], 3),
            "sortino": round(r["sortino"], 3),
            "ann_turnover": round(r["ann_turnover"], 2),
            "rebalances_per_year": round(r["rebalances_per_year"], 1),
            "total_growth": round(r["total_growth"], 3),
            "ann_tx_cost": round(r["ann_tx_cost"], 6),
        }

# Cross-OOS
for pname in oos_results:
    output["cross_oos_results"][pname] = {}
    for strat_name in strat_names:
        output["cross_oos_results"][pname][strat_name] = {}
        for cost in [0, 5]:
            r = oos_results[pname][strat_name][cost]
            output["cross_oos_results"][pname][strat_name][str(cost)] = {
                "sharpe": round(r["sharpe"], 4),
                "ann_return": round(r["ann_return"], 4),
                "max_dd": round(r["max_dd"], 4),
            }

out_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-aa93f5b7/experiments/k279_weekly_vt_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"  Results saved to {out_path}")

print("\n" + "=" * 80)
print("K279 COMPLETE")
print("=" * 80)
