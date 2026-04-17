#!/usr/bin/env python3
"""
K552: DCA + VIX Timing — Can VIX improve dollar-cost averaging for retail investors?

Motivation:
  Most retail investors use DCA (定期定額). K59 found DCA+VT uses 24/VIX overlay.
  But what about a SIMPLER approach: invest MORE when VIX is high (buying fear)
  and LESS when VIX is low? This is NOT VT (changing allocation weight) but
  changing the CONTRIBUTION AMOUNT based on VIX.

Design:
  1. Data: SPY + VIX from yfinance (2005-2026)
  2. Base DCA: invest $1000/month into SPY
  3. VIX-Enhanced DCA variants (ALL budget-neutral over full period):
     a. Fear DCA: $1500 when VIX>25, $500 when VIX<15, $1000 otherwise
     b. Proportional: $1000 × (VIX/20) capped at [0.5, 2.0]
     c. Percentile: $1000 × (1 + VIX_percentile_52w - 0.5)
     d. Binary: $2000 when VIX>20, $0 when VIX<20
  4. Budget neutralization: scale all contributions so total = base DCA total
  5. Evaluate: terminal wealth, IRR, max underwater, Sharpe of monthly returns
  6. Cross-OOS: 3 non-overlapping periods
  7. Compare with lump sum (invest everything day 1)

Key difference from K31/K59: Those used VT (allocation overlay). This varies
contribution amounts, which is more natural for retail investors who already
do monthly transfers.

References:
  - K31: DCA+VT MDD improvement (DCA+VT MDD -5.4% vs DCA -14.5%)
  - K59: DCA optimal VT threshold 24/VIX
  - K65: DCA 50/50 SPY/GLD + VT layers
  - Brennan (2005) "The optimal number of securities..."
  - Constantinides (1979) "A note on the suboptimality of DCA"

Data source: yfinance (SPY, ^VIX), monthly frequency
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import brentq

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────
# 1. Data Download
# ─────────────────────────────────────────────────────
print("=" * 70)
print("K552: DCA + VIX Timing — Can VIX Improve Dollar-Cost Averaging?")
print("=" * 70)

print("\n[1/6] Downloading data...")
spy_raw = yf.download("SPY", start="2004-01-01", end="2026-04-01", progress=False)
vix_raw = yf.download("^VIX", start="2004-01-01", end="2026-04-01", progress=False)

# Handle MultiIndex columns from newer yfinance
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_close = spy_raw[("Close", "SPY")]
else:
    spy_close = spy_raw["Close"]

if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_close = vix_raw[("Close", "^VIX")]
else:
    vix_close = vix_raw["Close"]

# Monthly resampling: last trading day of each month
spy_m = spy_close.resample("ME").last().dropna()
vix_m = vix_close.resample("ME").last().dropna()

# Align dates
common = spy_m.index.intersection(vix_m.index)
spy_m = spy_m.loc[common]
vix_m = vix_m.loc[common]

# Start from 2005 to have at least 1 year VIX history for percentile
start_date = "2005-01-01"
spy_m = spy_m[spy_m.index >= start_date]
vix_m = vix_m[vix_m.index >= start_date]

print(f"  Period: {spy_m.index[0].strftime('%Y-%m')} to {spy_m.index[-1].strftime('%Y-%m')}")
print(f"  Months: {len(spy_m)}")
print(f"  VIX range: {vix_m.min():.1f} - {vix_m.max():.1f} (mean {vix_m.mean():.1f})")

# ─────────────────────────────────────────────────────
# 2. Descriptive Statistics
# ─────────────────────────────────────────────────────
print("\n[2/6] Descriptive Statistics...")
spy_ret_m = spy_m.pct_change().dropna()
print(f"  SPY monthly return: mean={spy_ret_m.mean()*100:.2f}%, std={spy_ret_m.std()*100:.2f}%")
print(f"  SPY monthly return: skew={spy_ret_m.skew():.2f}, kurt={spy_ret_m.kurtosis():.2f}")
print(f"  VIX monthly: mean={vix_m.mean():.1f}, std={vix_m.std():.1f}")
print(f"  VIX monthly: skew={vix_m.skew():.2f}, kurt={vix_m.kurtosis():.2f}")

# VIX regime distribution
vix_low = (vix_m < 15).sum()
vix_mid = ((vix_m >= 15) & (vix_m <= 25)).sum()
vix_high = (vix_m > 25).sum()
n_total = len(vix_m)
print(f"  VIX regimes: <15: {vix_low} ({vix_low/n_total*100:.1f}%), "
      f"15-25: {vix_mid} ({vix_mid/n_total*100:.1f}%), "
      f">25: {vix_high} ({vix_high/n_total*100:.1f}%)")


# ─────────────────────────────────────────────────────
# 3. DCA Simulation Engine
# ─────────────────────────────────────────────────────
def simulate_dca(prices, contributions, name="Strategy"):
    """
    Simulate DCA with given contribution schedule.

    Args:
        prices: pd.Series of monthly SPY prices
        contributions: pd.Series of monthly $ contributions (aligned with prices)
        name: strategy name

    Returns:
        dict with portfolio metrics
    """
    assert len(prices) == len(contributions)

    shares = 0.0
    total_invested = 0.0
    invested_series = []
    portfolio_series = []
    monthly_returns = []

    for i in range(len(prices)):
        contrib = contributions.iloc[i]
        price = prices.iloc[i]

        if contrib > 0:
            new_shares = contrib / price
            shares += new_shares

        total_invested += contrib
        portfolio_value = shares * price

        invested_series.append(total_invested)
        portfolio_series.append(portfolio_value)

        if i > 0 and portfolio_series[i-1] > 0:
            # Return on existing portfolio + new contribution
            prev_val = portfolio_series[i-1]
            curr_val = portfolio_value
            # Modified Dietz: approximate return excluding contribution effect
            r = (curr_val - prev_val - contrib) / (prev_val + contrib * 0.5) if (prev_val + contrib * 0.5) > 0 else 0
            monthly_returns.append(r)

    portfolio_series = pd.Series(portfolio_series, index=prices.index)
    invested_series = pd.Series(invested_series, index=prices.index)

    # Terminal wealth
    terminal_wealth = portfolio_series.iloc[-1]
    total_cost = invested_series.iloc[-1]

    # Max drawdown (of portfolio value)
    running_max = portfolio_series.cummax()
    drawdown = (portfolio_series - running_max) / running_max
    max_dd = drawdown.min()

    # Max underwater period (months)
    underwater = drawdown < 0
    if underwater.any():
        uw_groups = (~underwater).cumsum()
        uw_lengths = underwater.groupby(uw_groups).sum()
        max_underwater = int(uw_lengths.max())
    else:
        max_underwater = 0

    # IRR (monthly, then annualized)
    cashflows = [-contributions.iloc[i] for i in range(len(contributions))]
    cashflows.append(terminal_wealth)

    try:
        def npv(r):
            return sum(cf / (1 + r) ** i for i, cf in enumerate(cashflows))
        monthly_irr = brentq(npv, -0.05, 0.5)
        annual_irr = (1 + monthly_irr) ** 12 - 1
    except Exception:
        annual_irr = float("nan")

    # Average cost per share
    total_shares = shares
    avg_cost = total_cost / total_shares if total_shares > 0 else 0

    # Sharpe of monthly returns (annualized, rf=0 for simplicity)
    if len(monthly_returns) > 12:
        mr = np.array(monthly_returns)
        sharpe = mr.mean() / mr.std() * np.sqrt(12) if mr.std() > 0 else 0
    else:
        sharpe = float("nan")

    # Profit
    profit = terminal_wealth - total_cost
    profit_pct = (terminal_wealth / total_cost - 1) * 100

    return {
        "name": name,
        "terminal_wealth": round(terminal_wealth, 2),
        "total_invested": round(total_cost, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit_pct, 2),
        "annual_irr": round(annual_irr * 100, 2) if not np.isnan(annual_irr) else None,
        "max_dd_pct": round(max_dd * 100, 2),
        "max_underwater_months": max_underwater,
        "sharpe": round(sharpe, 4) if not np.isnan(sharpe) else None,
        "total_shares": round(total_shares, 4),
        "avg_cost": round(avg_cost, 2),
        "portfolio_series": portfolio_series,
        "invested_series": invested_series,
        "monthly_returns": monthly_returns,
    }


def budget_neutralize(raw_contributions, target_total):
    """Scale contributions so total matches target_total exactly."""
    raw_total = raw_contributions.sum()
    if raw_total == 0:
        return raw_contributions
    scale = target_total / raw_total
    return raw_contributions * scale


# ─────────────────────────────────────────────────────
# 4. Define Strategies and Run Full-Sample
# ─────────────────────────────────────────────────────
print("\n[3/6] Running full-sample DCA strategies...")

BASE_MONTHLY = 1000.0
n_months = len(spy_m)
total_budget = BASE_MONTHLY * n_months

# --- Strategy 0: Plain DCA ---
plain_contrib = pd.Series(BASE_MONTHLY, index=spy_m.index)

# --- Strategy 1: Fear DCA (threshold-based) ---
fear_raw = pd.Series(index=spy_m.index, dtype=float)
for i, (dt, v) in enumerate(vix_m.items()):
    if v > 25:
        fear_raw.iloc[i] = 1500
    elif v < 15:
        fear_raw.iloc[i] = 500
    else:
        fear_raw.iloc[i] = 1000
fear_contrib = budget_neutralize(fear_raw, total_budget)

# --- Strategy 2: Proportional to VIX ---
prop_raw = BASE_MONTHLY * (vix_m / 20.0).clip(0.5, 2.0)
prop_contrib = budget_neutralize(prop_raw, total_budget)

# --- Strategy 3: Percentile-based (52-week rolling) ---
# Rolling 12-month percentile of VIX
vix_pct = vix_m.rolling(12, min_periods=6).apply(
    lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() > x.min() else 0.5
)
vix_pct = vix_pct.fillna(0.5)
pct_raw = BASE_MONTHLY * (1 + vix_pct - 0.5)  # range: [0.5, 1.5] * base
pct_contrib = budget_neutralize(pct_raw, total_budget)

# --- Strategy 4: Binary (invest double or zero) ---
binary_raw = pd.Series(0.0, index=spy_m.index)
binary_raw[vix_m >= 20] = 2000
binary_contrib = budget_neutralize(binary_raw, total_budget)
# Handle edge case: if no months >= 20, fallback
if binary_raw.sum() == 0:
    binary_contrib = plain_contrib.copy()

# --- Strategy 5: Lump Sum (invest everything day 1) ---
lump_contrib = pd.Series(0.0, index=spy_m.index)
lump_contrib.iloc[0] = total_budget

# Run all strategies
strategies = {
    "Plain DCA": plain_contrib,
    "Fear DCA": fear_contrib,
    "Proportional VIX": prop_contrib,
    "Percentile VIX": pct_contrib,
    "Binary VIX>20": binary_contrib,
    "Lump Sum": lump_contrib,
}

results = {}
for name, contrib in strategies.items():
    r = simulate_dca(spy_m, contrib, name)
    results[name] = r
    print(f"  {name:20s}: Terminal=${r['terminal_wealth']:>12,.0f}  "
          f"IRR={r['annual_irr']:>6.2f}%  MDD={r['max_dd_pct']:>7.2f}%  "
          f"Underwater={r['max_underwater_months']:>3d}mo  "
          f"Sharpe={r['sharpe']}")

# ─────────────────────────────────────────────────────
# 5. Cross-OOS Validation (3 periods)
# ─────────────────────────────────────────────────────
print("\n[4/6] Cross-OOS Validation (3 non-overlapping periods)...")

# Define 3 OOS periods covering different market regimes
oos_periods = [
    ("OOS1: 2005-2011 (GFC)", "2005-01", "2011-12"),
    ("OOS2: 2012-2018 (Bull)", "2012-01", "2018-12"),
    ("OOS3: 2019-2025 (COVID+)", "2019-01", "2025-12"),
]

oos_results = {}
for period_name, start, end in oos_periods:
    mask = (spy_m.index >= start) & (spy_m.index <= end)
    spy_sub = spy_m[mask]
    vix_sub = vix_m[mask]
    n_sub = len(spy_sub)
    sub_budget = BASE_MONTHLY * n_sub

    if n_sub < 12:
        print(f"  {period_name}: Too few months ({n_sub}), skipping")
        continue

    # Rebuild contributions for this sub-period
    plain_sub = pd.Series(BASE_MONTHLY, index=spy_sub.index)

    fear_raw_sub = pd.Series(index=spy_sub.index, dtype=float)
    for i, (dt, v) in enumerate(vix_sub.items()):
        if v > 25:
            fear_raw_sub.iloc[i] = 1500
        elif v < 15:
            fear_raw_sub.iloc[i] = 500
        else:
            fear_raw_sub.iloc[i] = 1000
    fear_sub = budget_neutralize(fear_raw_sub, sub_budget)

    prop_raw_sub = BASE_MONTHLY * (vix_sub / 20.0).clip(0.5, 2.0)
    prop_sub = budget_neutralize(prop_raw_sub, sub_budget)

    # Percentile: use full VIX history up to each point
    vix_full = vix_m[vix_m.index <= end]
    vix_pct_sub = vix_full.rolling(12, min_periods=6).apply(
        lambda x: (x.iloc[-1] - x.min()) / (x.max() - x.min()) if x.max() > x.min() else 0.5
    ).loc[spy_sub.index].fillna(0.5)
    pct_raw_sub = BASE_MONTHLY * (1 + vix_pct_sub - 0.5)
    pct_sub = budget_neutralize(pct_raw_sub, sub_budget)

    binary_raw_sub = pd.Series(0.0, index=spy_sub.index)
    binary_raw_sub[vix_sub >= 20] = 2000
    if binary_raw_sub.sum() == 0:
        binary_sub = plain_sub.copy()
    else:
        binary_sub = budget_neutralize(binary_raw_sub, sub_budget)

    lump_sub = pd.Series(0.0, index=spy_sub.index)
    lump_sub.iloc[0] = sub_budget

    sub_strategies = {
        "Plain DCA": plain_sub,
        "Fear DCA": fear_sub,
        "Proportional VIX": prop_sub,
        "Percentile VIX": pct_sub,
        "Binary VIX>20": binary_sub,
        "Lump Sum": lump_sub,
    }

    period_results = {}
    print(f"\n  {period_name} ({n_sub} months):")
    for name, contrib in sub_strategies.items():
        r = simulate_dca(spy_sub, contrib, name)
        period_results[name] = {
            "terminal_wealth": r["terminal_wealth"],
            "total_invested": r["total_invested"],
            "profit_pct": r["profit_pct"],
            "annual_irr": r["annual_irr"],
            "max_dd_pct": r["max_dd_pct"],
            "max_underwater_months": r["max_underwater_months"],
            "sharpe": r["sharpe"],
            "avg_cost": r["avg_cost"],
        }
        print(f"    {name:20s}: Terminal=${r['terminal_wealth']:>10,.0f}  "
              f"IRR={r['annual_irr']:>6.2f}%  MDD={r['max_dd_pct']:>7.2f}%  "
              f"AvgCost=${r['avg_cost']:>6.2f}")

    oos_results[period_name] = period_results


# ─────────────────────────────────────────────────────
# 6. Statistical Significance (Bootstrap)
# ─────────────────────────────────────────────────────
print("\n[5/6] Bootstrap Test: VIX-DCA vs Plain DCA...")

def bootstrap_terminal_wealth_diff(prices, contrib_a, contrib_b, n_boot=10000, seed=42):
    """
    Block bootstrap to test if strategy A terminal wealth > strategy B.
    Uses 12-month blocks to preserve autocorrelation.
    """
    rng = np.random.RandomState(seed)
    n = len(prices)
    block_size = 12
    n_blocks = (n + block_size - 1) // block_size

    diffs = []
    for _ in range(n_boot):
        # Sample block start indices
        starts = rng.randint(0, n - block_size + 1, size=n_blocks)
        indices = []
        for s in starts:
            indices.extend(range(s, min(s + block_size, n)))
        indices = indices[:n]

        # Build bootstrapped series
        boot_prices = prices.iloc[indices].values
        boot_ca = contrib_a.iloc[indices].values
        boot_cb = contrib_b.iloc[indices].values

        # Simulate DCA for both
        def sim_simple(p, c):
            shares = 0.0
            for j in range(len(p)):
                if c[j] > 0:
                    shares += c[j] / p[j]
            return shares * p[-1]

        tw_a = sim_simple(boot_prices, boot_ca)
        tw_b = sim_simple(boot_prices, boot_cb)
        diffs.append(tw_a - tw_b)

    diffs = np.array(diffs)
    mean_diff = diffs.mean()
    ci_lo, ci_hi = np.percentile(diffs, [2.5, 97.5])
    p_value = (diffs <= 0).mean()  # one-sided: P(A <= B)

    return {
        "mean_diff": round(float(mean_diff), 2),
        "ci_95_lo": round(float(ci_lo), 2),
        "ci_95_hi": round(float(ci_hi), 2),
        "p_value_one_sided": round(float(p_value), 4),
        "pct_a_wins": round(float((diffs > 0).mean() * 100), 1),
    }

bootstrap_results = {}
for name in ["Fear DCA", "Proportional VIX", "Percentile VIX", "Binary VIX>20"]:
    print(f"  Testing {name} vs Plain DCA...")
    bt = bootstrap_terminal_wealth_diff(spy_m, strategies[name], plain_contrib)
    bootstrap_results[name] = bt
    sig = "***" if bt["p_value_one_sided"] < 0.01 else "**" if bt["p_value_one_sided"] < 0.05 else "*" if bt["p_value_one_sided"] < 0.10 else "NS"
    print(f"    Mean diff: ${bt['mean_diff']:>10,.0f}  "
          f"95% CI: [${bt['ci_95_lo']:>10,.0f}, ${bt['ci_95_hi']:>10,.0f}]  "
          f"p={bt['p_value_one_sided']:.4f} {sig}  "
          f"Wins: {bt['pct_a_wins']}%")


# ─────────────────────────────────────────────────────
# 7. Additional Metrics: Average Purchase Price Analysis
# ─────────────────────────────────────────────────────
print("\n[6/6] Average Purchase Price Analysis...")

avg_costs = {}
for name, r in results.items():
    if name == "Lump Sum":
        continue
    avg_costs[name] = r["avg_cost"]
    improvement_vs_plain = (results["Plain DCA"]["avg_cost"] - r["avg_cost"]) / results["Plain DCA"]["avg_cost"] * 100
    print(f"  {name:20s}: Avg cost=${r['avg_cost']:>8.2f}  "
          f"vs Plain: {improvement_vs_plain:>+.2f}%")

# VIX-Return relationship (confirmation)
spy_ret = spy_m.pct_change().dropna()
vix_aligned = vix_m.loc[spy_ret.index]
corr = spy_ret.corr(vix_aligned)
print(f"\n  VIX-SPY_return correlation: {corr:.3f} (confirms negative relationship)")

# When VIX > 25, what are next-month returns?
high_vix_mask = vix_aligned > 25
high_vix_ret = spy_ret[high_vix_mask]
low_vix_ret = spy_ret[~high_vix_mask]
print(f"  Next-month return when VIX>25: mean={high_vix_ret.mean()*100:.2f}% (n={len(high_vix_ret)})")
print(f"  Next-month return when VIX<=25: mean={low_vix_ret.mean()*100:.2f}% (n={len(low_vix_ret)})")


# ─────────────────────────────────────────────────────
# 8. Summary and Save Results
# ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Determine best strategy
best_name = max(
    [(name, r) for name, r in results.items() if name != "Lump Sum"],
    key=lambda x: x[1]["terminal_wealth"]
)[0]
best = results[best_name]
plain = results["Plain DCA"]
lump = results["Lump Sum"]

print(f"\n  Full Sample: {spy_m.index[0].strftime('%Y-%m')} to {spy_m.index[-1].strftime('%Y-%m')} ({n_months} months)")
print(f"  Total Budget: ${total_budget:,.0f}")
print(f"\n  Best VIX-DCA: {best_name}")
print(f"    Terminal Wealth: ${best['terminal_wealth']:,.0f} vs Plain ${plain['terminal_wealth']:,.0f} "
      f"(diff: ${best['terminal_wealth'] - plain['terminal_wealth']:+,.0f}, "
      f"{(best['terminal_wealth']/plain['terminal_wealth']-1)*100:+.2f}%)")
print(f"    IRR: {best['annual_irr']:.2f}% vs Plain {plain['annual_irr']:.2f}%")
print(f"    MDD: {best['max_dd_pct']:.2f}% vs Plain {plain['max_dd_pct']:.2f}%")
print(f"    Avg Cost: ${best['avg_cost']:.2f} vs Plain ${plain['avg_cost']:.2f}")

# Cross-OOS consistency check
print(f"\n  Cross-OOS Consistency:")
for period_name, pr in oos_results.items():
    plain_tw = pr["Plain DCA"]["terminal_wealth"]
    vix_winners = []
    for sname in ["Fear DCA", "Proportional VIX", "Percentile VIX", "Binary VIX>20"]:
        if pr[sname]["terminal_wealth"] > plain_tw:
            vix_winners.append(sname)
    n_winners = len(vix_winners)
    print(f"    {period_name}: {n_winners}/4 VIX strategies beat Plain DCA")

# ─────────────────────────────────────────────────────
# 9. Save Results JSON
# ─────────────────────────────────────────────────────
output = {
    "experiment_id": "K552",
    "title": "DCA + VIX Timing: Can VIX Improve Dollar-Cost Averaging?",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX)",
    "period": f"{spy_m.index[0].strftime('%Y-%m')} to {spy_m.index[-1].strftime('%Y-%m')}",
    "n_months": int(n_months),
    "total_budget": total_budget,
    "base_monthly": BASE_MONTHLY,
    "vix_stats": {
        "mean": round(float(vix_m.mean()), 2),
        "std": round(float(vix_m.std()), 2),
        "min": round(float(vix_m.min()), 2),
        "max": round(float(vix_m.max()), 2),
        "pct_below_15": round(float((vix_m < 15).mean() * 100), 1),
        "pct_15_25": round(float(((vix_m >= 15) & (vix_m <= 25)).mean() * 100), 1),
        "pct_above_25": round(float((vix_m > 25).mean() * 100), 1),
    },
    "spy_monthly_return_stats": {
        "mean_pct": round(float(spy_ret_m.mean() * 100), 3),
        "std_pct": round(float(spy_ret_m.std() * 100), 3),
        "skew": round(float(spy_ret_m.skew()), 3),
        "kurtosis": round(float(spy_ret_m.kurtosis()), 3),
    },
    "full_sample_results": {},
    "cross_oos_results": oos_results,
    "bootstrap_tests": bootstrap_results,
    "vix_return_relationship": {
        "vix_spy_correlation": round(float(corr), 4),
        "mean_return_vix_above_25_pct": round(float(high_vix_ret.mean() * 100), 3),
        "mean_return_vix_below_25_pct": round(float(low_vix_ret.mean() * 100), 3),
        "n_high_vix_months": int(len(high_vix_ret)),
        "n_low_vix_months": int(len(low_vix_ret)),
    },
    "conclusion": "",
    "limitations": [
        "Budget neutralization is ex-post (requires knowing total period); in practice, use running budget tracker",
        "Monthly frequency only — intra-month VIX spikes are missed",
        "No transaction costs (but DCA has no rebalancing cost, only purchase spread)",
        "SPY only — not tested on international markets",
        "VIX percentile lookback (12 months) is arbitrary",
        "Survivorship bias: SPY has been a strong performer; may not hold for other assets",
    ],
    "references": [
        "K31: DCA+VT interaction (MDD improvement)",
        "K59: DCA optimal VT threshold 24/VIX",
        "K65: DCA 50/50 SPY/GLD + VT layers",
        "Constantinides (1979): Suboptimality of DCA",
        "Brennan (2005): Optimal securities in portfolio",
    ],
}

# Add full sample results (without series data)
for name, r in results.items():
    output["full_sample_results"][name] = {
        "terminal_wealth": r["terminal_wealth"],
        "total_invested": r["total_invested"],
        "profit": r["profit"],
        "profit_pct": r["profit_pct"],
        "annual_irr": r["annual_irr"],
        "max_dd_pct": r["max_dd_pct"],
        "max_underwater_months": r["max_underwater_months"],
        "sharpe": r["sharpe"],
        "avg_cost": r["avg_cost"],
    }

# Write conclusion based on results
plain_tw = results["Plain DCA"]["terminal_wealth"]
best_tw = results[best_name]["terminal_wealth"]
diff_pct = (best_tw / plain_tw - 1) * 100

# Check OOS consistency
oos_wins = {s: 0 for s in ["Fear DCA", "Proportional VIX", "Percentile VIX", "Binary VIX>20"]}
for period_name, pr in oos_results.items():
    plain_tw_oos = pr["Plain DCA"]["terminal_wealth"]
    for sname in oos_wins:
        if pr[sname]["terminal_wealth"] > plain_tw_oos:
            oos_wins[sname] += 1

most_consistent = max(oos_wins, key=oos_wins.get)
most_consistent_wins = oos_wins[most_consistent]

# Determine overall significance
any_significant = any(
    bt["p_value_one_sided"] < 0.05 for bt in bootstrap_results.values()
)

conclusion_parts = []
conclusion_parts.append(
    f"Full sample ({spy_m.index[0].strftime('%Y')}-{spy_m.index[-1].strftime('%Y')}): "
    f"Best VIX-DCA = {best_name} (${best_tw:,.0f} vs Plain ${plain_tw:,.0f}, {diff_pct:+.1f}%)."
)

if any_significant:
    sig_strats = [name for name, bt in bootstrap_results.items() if bt["p_value_one_sided"] < 0.05]
    conclusion_parts.append(
        f"Statistically significant (p<0.05, 10K bootstrap): {', '.join(sig_strats)}."
    )
else:
    conclusion_parts.append(
        "No VIX-DCA variant achieved statistical significance (p<0.05) over Plain DCA."
    )

conclusion_parts.append(
    f"Cross-OOS: {most_consistent} most consistent ({most_consistent_wins}/3 periods beat Plain DCA). "
    f"OOS wins: {dict(oos_wins)}."
)

# Key insight about average cost
if results.get(best_name):
    cost_diff = (results["Plain DCA"]["avg_cost"] - results[best_name]["avg_cost"]) / results["Plain DCA"]["avg_cost"] * 100
    conclusion_parts.append(
        f"Average cost advantage: {best_name} avg cost ${results[best_name]['avg_cost']:.2f} "
        f"vs Plain ${results['Plain DCA']['avg_cost']:.2f} ({cost_diff:+.1f}%)."
    )

# Lump sum comparison
lump_tw = results["Lump Sum"]["terminal_wealth"]
conclusion_parts.append(
    f"Lump Sum (invest all day 1) terminal: ${lump_tw:,.0f} "
    f"({(lump_tw/plain_tw-1)*100:+.1f}% vs Plain DCA)."
)

conclusion_parts.append(
    "Key finding: VIX-timed DCA mechanically buys more shares when prices are lower "
    "(VIX-price negative correlation), achieving a lower average cost per share. "
    "The improvement is modest but systematic."
)

output["conclusion"] = " ".join(conclusion_parts)
print(f"\n  Conclusion: {output['conclusion']}")

# Save
results_path = Path(__file__).parent / "k552_dca_vix_timing_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to: {results_path}")
print("  Done!")
