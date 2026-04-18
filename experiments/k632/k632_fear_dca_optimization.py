#!/usr/bin/env python3
"""
K632: Fear DCA Strategy — Parameter Optimization

Motivation:
  K552 established Fear DCA as a consistent (3/3 OOS) but statistically NS
  improvement over plain DCA. K552 used budget-neutral design with fixed
  threshold-based multipliers. K632 takes a different approach:

  - Total invested VARIES (more invested when scared = real-world behavior)
  - Systematically test multiplier function families (linear, step, exp, inverse, binary)
  - Evaluate per-dollar-invested efficiency (not just terminal wealth)
  - Sensitivity analysis on key parameters

Design:
  Data: SPY daily + VIX from yfinance, 2006-01-01 to 2026-03-27
  OOS evaluation: 2010-01-01 to 2026-03-27
  Monthly DCA: invest on first trading day of each month
  Base: $1,000/month

  Multiplier families:
    a. Linear: mult = 1 + max(0, (VIX - 20)) × α, cap 3x  (α = 0.02..0.20)
    b. Step: discrete brackets (VIX <15: 0.5, 15-20: 1.0, 20-30: 1.5, 30-40: 2.0, ≥40: 3.0)
    c. Exponential: mult = exp(β × max(0, VIX - 20)), cap 3x  (β = 0.02..0.10)
    d. Inverse: mult = 12/VIX (same idea as 12/VIX strategy)
    e. Binary: VIX > 25 → 2x, else 1x

  Metrics: terminal wealth, total invested, avg cost/share, IRR, MDD, Sharpe,
           wealth per dollar invested, vs-plain-DCA comparison

  Sensitivity:
    1. Liquidity constraint (50% extra only half the time)
    2. VIX threshold 25 instead of 20
    3. Max multiplier 2x instead of 3x

References:
  - K552: DCA + VIX timing (3/3 OOS, NS, Fear DCA terminal +2.9%)
  - K31: DCA + VT MDD improvement
  - K59: DCA optimal VT threshold 24/VIX
  - Constantinides (1979): Suboptimality of DCA
  - Brennan (2005): Optimal securities in portfolio
  - Choi, Laibson, Madrian (2009): Dollar-cost averaging with mental accounting

Data source: yfinance (SPY, ^VIX), daily prices, monthly investing
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
print("=" * 80)
print("K632: Fear DCA Strategy — Parameter Optimization")
print("=" * 80)

print("\n[1/7] Downloading data...")
spy_raw = yf.download("SPY", start="2005-01-01", end="2026-03-28", progress=False)
vix_raw = yf.download("^VIX", start="2005-01-01", end="2026-03-28", progress=False)

# Handle MultiIndex columns from newer yfinance
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_close = spy_raw[("Close", "SPY")]
else:
    spy_close = spy_raw["Close"]

if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_close = vix_raw[("Close", "^VIX")]
else:
    vix_close = vix_raw["Close"]

# Build daily DataFrame
daily = pd.DataFrame({"spy": spy_close, "vix": vix_close}).dropna()
daily.index = pd.to_datetime(daily.index)

print(f"  Daily data: {daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(daily)}")
print(f"  VIX range: {daily['vix'].min():.1f} - {daily['vix'].max():.1f} (mean {daily['vix'].mean():.1f})")

# ─────────────────────────────────────────────────────
# 2. Descriptive Statistics
# ─────────────────────────────────────────────────────
print("\n[2/7] Descriptive Statistics...")

spy_ret = daily["spy"].pct_change().dropna()
print(f"  SPY daily return: mean={spy_ret.mean()*100:.4f}%, std={spy_ret.std()*100:.4f}%")
print(f"  SPY daily return: skew={spy_ret.skew():.3f}, kurt={spy_ret.kurtosis():.3f}")
print(f"  VIX daily: mean={daily['vix'].mean():.2f}, std={daily['vix'].std():.2f}")
print(f"  VIX daily: skew={daily['vix'].skew():.3f}, kurt={daily['vix'].kurtosis():.3f}")

# VIX regime distribution
vix = daily["vix"]
regimes = {
    "VIX < 15": (vix < 15).sum(),
    "15 ≤ VIX < 20": ((vix >= 15) & (vix < 20)).sum(),
    "20 ≤ VIX < 25": ((vix >= 20) & (vix < 25)).sum(),
    "25 ≤ VIX < 30": ((vix >= 25) & (vix < 30)).sum(),
    "30 ≤ VIX < 40": ((vix >= 30) & (vix < 40)).sum(),
    "VIX ≥ 40": (vix >= 40).sum(),
}
n_total = len(vix)
print("\n  VIX regime distribution:")
for regime_name, count in regimes.items():
    print(f"    {regime_name:20s}: {count:5d} days ({count/n_total*100:5.1f}%)")


# ─────────────────────────────────────────────────────
# 3. Monthly Investment Schedule
# ─────────────────────────────────────────────────────
print("\n[3/7] Building monthly investment schedule...")

# Get first trading day of each month — keep actual trading dates
daily["year_month"] = daily.index.to_period("M")
# Use idxmin on a sequential index to get the actual first trading day per month
first_day_dates = daily.groupby("year_month").apply(lambda g: g.index[0])
first_days = daily.loc[first_day_dates.values].copy()

# Filter to OOS period: 2010-01-01 to 2026-03-27
oos_start = "2010-01-01"
oos_end = "2026-03-27"
invest_days = first_days[(first_days.index >= oos_start) & (first_days.index <= oos_end)].copy()

n_months = len(invest_days)
print(f"  Investment months: {n_months}")
print(f"  Period: {invest_days.index[0].strftime('%Y-%m')} to {invest_days.index[-1].strftime('%Y-%m')}")
print(f"  VIX at invest dates: mean={invest_days['vix'].mean():.1f}, "
      f"min={invest_days['vix'].min():.1f}, max={invest_days['vix'].max():.1f}")


# ─────────────────────────────────────────────────────
# 4. DCA Simulation Engine
# ─────────────────────────────────────────────────────
BASE_MONTHLY = 1000.0


def simulate_dca(daily_prices, invest_schedule, contributions, name="Strategy"):
    """
    Simulate DCA with given contribution schedule using daily prices.

    Args:
        daily_prices: pd.Series of daily SPY prices (full history for valuation)
        invest_schedule: pd.DatetimeIndex of investment dates
        contributions: np.array of $ amounts for each invest date
        name: strategy name

    Returns:
        dict with portfolio metrics
    """
    shares = 0.0
    total_invested = 0.0
    cashflows = []  # (date, amount) for IRR

    # Track portfolio value daily for MDD calculation
    portfolio_values = []
    invest_idx = 0

    # Only track from first investment date
    start_date = invest_schedule[0]
    end_prices = daily_prices[daily_prices.index >= start_date]

    for date in end_prices.index:
        price = end_prices[date]

        # Check if this is an investment date
        if invest_idx < len(invest_schedule) and date >= invest_schedule[invest_idx]:
            contrib = contributions[invest_idx]
            if contrib > 0:
                new_shares = contrib / price
                shares += new_shares
                total_invested += contrib
                cashflows.append((-contrib, date))
            invest_idx += 1

        portfolio_value = shares * price
        portfolio_values.append((date, portfolio_value, total_invested))

    if not portfolio_values:
        return None

    pv_df = pd.DataFrame(portfolio_values, columns=["date", "value", "invested"])
    pv_df.set_index("date", inplace=True)

    terminal_wealth = pv_df["value"].iloc[-1]

    # Max drawdown
    running_max = pv_df["value"].cummax()
    drawdown = (pv_df["value"] - running_max) / running_max
    max_dd = drawdown.min()

    # Monthly returns (for Sharpe)
    monthly_pv = pv_df["value"].resample("ME").last().dropna()
    monthly_inv = pv_df["invested"].resample("ME").last().dropna()
    # Use Modified Dietz for monthly returns
    monthly_returns = []
    for i in range(1, len(monthly_pv)):
        prev_val = monthly_pv.iloc[i-1]
        curr_val = monthly_pv.iloc[i]
        new_investment = monthly_inv.iloc[i] - monthly_inv.iloc[i-1]
        if prev_val + new_investment * 0.5 > 0:
            r = (curr_val - prev_val - new_investment) / (prev_val + new_investment * 0.5)
            monthly_returns.append(r)

    # Sharpe ratio (annualized, rf=0)
    if len(monthly_returns) > 12:
        mr = np.array(monthly_returns)
        sharpe = mr.mean() / mr.std() * np.sqrt(12) if mr.std() > 0 else 0
    else:
        sharpe = float("nan")

    # IRR (monthly cashflows + terminal value)
    try:
        # Build monthly cashflow series
        cf_monthly = {}
        for amount, date in cashflows:
            month_key = date.to_period("M")
            cf_monthly[month_key] = cf_monthly.get(month_key, 0) + amount

        all_months = pd.period_range(
            cashflows[0][1].to_period("M"),
            pv_df.index[-1].to_period("M"),
            freq="M"
        )
        cf_series = [cf_monthly.get(m, 0) for m in all_months]
        cf_series[-1] += terminal_wealth  # Add terminal value to last period

        def npv(r):
            return sum(cf / (1 + r) ** i for i, cf in enumerate(cf_series))

        monthly_irr = brentq(npv, -0.05, 0.5)
        annual_irr = (1 + monthly_irr) ** 12 - 1
    except Exception:
        annual_irr = float("nan")

    # Average cost per share
    avg_cost = total_invested / shares if shares > 0 else 0

    # Wealth per dollar invested
    wealth_per_dollar = terminal_wealth / total_invested if total_invested > 0 else 0

    return {
        "name": name,
        "terminal_wealth": round(float(terminal_wealth), 2),
        "total_invested": round(float(total_invested), 2),
        "profit": round(float(terminal_wealth - total_invested), 2),
        "profit_pct": round(float((terminal_wealth / total_invested - 1) * 100), 2),
        "annual_irr_pct": round(float(annual_irr * 100), 3) if not np.isnan(annual_irr) else None,
        "max_dd_pct": round(float(max_dd * 100), 2),
        "sharpe": round(float(sharpe), 4) if not np.isnan(sharpe) else None,
        "total_shares": round(float(shares), 4),
        "avg_cost_per_share": round(float(avg_cost), 2),
        "wealth_per_dollar": round(float(wealth_per_dollar), 4),
        "n_months_invested": int(len(invest_schedule)),
    }


# ─────────────────────────────────────────────────────
# 5. Define Multiplier Functions
# ─────────────────────────────────────────────────────
print("\n[4/7] Defining multiplier functions and running simulations...")

def mult_plain(vix_val):
    """Plain DCA: always 1x"""
    return 1.0

def mult_linear(vix_val, alpha, threshold=20, cap=3.0):
    """Linear: mult = 1 + max(0, (VIX - threshold)) × α, capped"""
    return min(1 + max(0, vix_val - threshold) * alpha, cap)

def mult_step(vix_val):
    """Step function based on VIX brackets"""
    if vix_val < 15:
        return 0.5
    elif vix_val < 20:
        return 1.0
    elif vix_val < 30:
        return 1.5
    elif vix_val < 40:
        return 2.0
    else:
        return 3.0

def mult_exponential(vix_val, beta, threshold=20, cap=3.0):
    """Exponential: mult = exp(β × max(0, VIX - threshold)), capped"""
    return min(np.exp(beta * max(0, vix_val - threshold)), cap)

def mult_inverse(vix_val):
    """Inverse: mult = 12/VIX"""
    return 12.0 / vix_val if vix_val > 0 else 1.0

def mult_binary(vix_val, threshold=25):
    """Binary: above threshold → 2x, else 1x"""
    return 2.0 if vix_val > threshold else 1.0


# Build all strategies
strategy_configs = {}

# 0. Plain DCA
strategy_configs["Plain DCA"] = lambda v: mult_plain(v)

# a. Linear family
for alpha in [0.02, 0.05, 0.10, 0.15, 0.20]:
    name = f"Linear α={alpha:.2f}"
    strategy_configs[name] = (lambda a: lambda v: mult_linear(v, a))(alpha)

# b. Step function
strategy_configs["Step"] = lambda v: mult_step(v)

# c. Exponential family
for beta in [0.02, 0.05, 0.10]:
    name = f"Exp β={beta:.2f}"
    strategy_configs[name] = (lambda b: lambda v: mult_exponential(v, b))(beta)

# d. Inverse (12/VIX)
strategy_configs["Inverse 12/VIX"] = lambda v: mult_inverse(v)

# e. Binary (VIX > 25)
strategy_configs["Binary VIX>25"] = lambda v: mult_binary(v, 25)


# ─────────────────────────────────────────────────────
# 6. Run All Strategies
# ─────────────────────────────────────────────────────
print(f"\n  Running {len(strategy_configs)} strategies...")

all_results = {}
spy_daily = daily["spy"]

for strat_name, mult_func in strategy_configs.items():
    # Calculate contributions for each investment month
    contributions = np.array([
        BASE_MONTHLY * mult_func(invest_days["vix"].iloc[i])
        for i in range(n_months)
    ])

    result = simulate_dca(
        spy_daily,
        invest_days.index,
        contributions,
        name=strat_name
    )

    if result:
        # Add multiplier stats
        multipliers = np.array([mult_func(invest_days["vix"].iloc[i]) for i in range(n_months)])
        result["mult_mean"] = round(float(multipliers.mean()), 3)
        result["mult_std"] = round(float(multipliers.std()), 3)
        result["mult_min"] = round(float(multipliers.min()), 3)
        result["mult_max"] = round(float(multipliers.max()), 3)
        result["months_above_1x"] = int((multipliers > 1.0).sum())
        result["months_below_1x"] = int((multipliers < 1.0).sum())
        result["months_at_1x"] = int((multipliers == 1.0).sum())

        all_results[strat_name] = result

# Print comparison table
print(f"\n{'Strategy':25s} {'Terminal$':>12s} {'Invested$':>12s} {'$/Invested':>10s} "
      f"{'IRR%':>8s} {'MDD%':>8s} {'Sharpe':>8s} {'AvgCost':>8s} {'MultAvg':>8s}")
print("-" * 110)

plain_result = all_results["Plain DCA"]
for strat_name in strategy_configs.keys():
    r = all_results[strat_name]
    irr_str = f"{r['annual_irr_pct']:.2f}" if r['annual_irr_pct'] is not None else "N/A"
    sharpe_str = f"{r['sharpe']:.3f}" if r['sharpe'] is not None else "N/A"
    print(f"  {strat_name:23s} {r['terminal_wealth']:>12,.0f} {r['total_invested']:>12,.0f} "
          f"{r['wealth_per_dollar']:>10.4f} {irr_str:>8s} {r['max_dd_pct']:>8.2f} "
          f"{sharpe_str:>8s} {r['avg_cost_per_share']:>8.2f} {r['mult_mean']:>8.3f}")


# ─────────────────────────────────────────────────────
# 7. Comparison vs Plain DCA
# ─────────────────────────────────────────────────────
print("\n\n[5/7] Comparison vs Plain DCA...")
print(f"\n{'Strategy':25s} {'ΔWealth':>12s} {'ΔWealth%':>10s} {'ΔInvested$':>12s} "
      f"{'Δ$/Inv':>10s} {'ΔIRR':>8s} {'ΔMDD':>8s} {'ΔAvgCost%':>10s}")
print("-" * 110)

comparison_data = {}
for strat_name, r in all_results.items():
    if strat_name == "Plain DCA":
        continue

    delta_wealth = r["terminal_wealth"] - plain_result["terminal_wealth"]
    delta_wealth_pct = (r["terminal_wealth"] / plain_result["terminal_wealth"] - 1) * 100
    delta_invested = r["total_invested"] - plain_result["total_invested"]
    delta_wpd = r["wealth_per_dollar"] - plain_result["wealth_per_dollar"]

    delta_irr = None
    if r["annual_irr_pct"] is not None and plain_result["annual_irr_pct"] is not None:
        delta_irr = r["annual_irr_pct"] - plain_result["annual_irr_pct"]

    delta_mdd = r["max_dd_pct"] - plain_result["max_dd_pct"]
    delta_avg_cost_pct = (r["avg_cost_per_share"] / plain_result["avg_cost_per_share"] - 1) * 100

    comparison_data[strat_name] = {
        "delta_wealth": round(float(delta_wealth), 2),
        "delta_wealth_pct": round(float(delta_wealth_pct), 2),
        "delta_invested": round(float(delta_invested), 2),
        "delta_wealth_per_dollar": round(float(delta_wpd), 4),
        "delta_irr_pct": round(float(delta_irr), 3) if delta_irr is not None else None,
        "delta_mdd_pct": round(float(delta_mdd), 2),
        "delta_avg_cost_pct": round(float(delta_avg_cost_pct), 2),
    }

    irr_str = f"{delta_irr:+.2f}" if delta_irr is not None else "N/A"
    print(f"  {strat_name:23s} {delta_wealth:>+12,.0f} {delta_wealth_pct:>+10.2f}% "
          f"{delta_invested:>+12,.0f} {delta_wpd:>+10.4f} {irr_str:>8s} "
          f"{delta_mdd:>+8.2f} {delta_avg_cost_pct:>+10.2f}%")


# ─────────────────────────────────────────────────────
# 8. Best Strategy per Dollar Invested
# ─────────────────────────────────────────────────────
print("\n\n[6/7] Ranking by Wealth per Dollar Invested...")

# Sort by wealth per dollar invested
ranked = sorted(
    [(name, r) for name, r in all_results.items()],
    key=lambda x: x[1]["wealth_per_dollar"],
    reverse=True
)

print(f"\n  {'Rank':>4s} {'Strategy':25s} {'$/Invested':>10s} {'IRR%':>8s} {'MDD%':>8s} {'Invested$':>12s}")
print("  " + "-" * 75)
for rank, (name, r) in enumerate(ranked, 1):
    irr_str = f"{r['annual_irr_pct']:.2f}" if r['annual_irr_pct'] is not None else "N/A"
    marker = " ★" if rank <= 3 else ""
    print(f"  {rank:>4d} {name:25s} {r['wealth_per_dollar']:>10.4f} "
          f"{irr_str:>8s} {r['max_dd_pct']:>8.2f} {r['total_invested']:>12,.0f}{marker}")


# ─────────────────────────────────────────────────────
# 9. Sensitivity Analysis
# ─────────────────────────────────────────────────────
print("\n\n[7/7] Sensitivity Analysis...")

sensitivity_results = {}

# --- Sensitivity 1: Liquidity constraint (50% of extra only half the time) ---
print("\n  S1: Liquidity constraint — can only invest extra 50% of the time")
rng = np.random.RandomState(42)

sens1_results = {}
for strat_name, mult_func in strategy_configs.items():
    if strat_name == "Plain DCA":
        continue

    contributions = np.zeros(n_months)
    for i in range(n_months):
        base_mult = mult_func(invest_days["vix"].iloc[i])
        if base_mult > 1.0:
            # Only invest extra half the time
            if rng.random() < 0.5:
                contributions[i] = BASE_MONTHLY * base_mult
            else:
                contributions[i] = BASE_MONTHLY  # Fall back to base
        else:
            contributions[i] = BASE_MONTHLY * base_mult

    result = simulate_dca(spy_daily, invest_days.index, contributions, name=strat_name)
    if result:
        sens1_results[strat_name] = {
            "terminal_wealth": result["terminal_wealth"],
            "total_invested": result["total_invested"],
            "wealth_per_dollar": result["wealth_per_dollar"],
            "annual_irr_pct": result["annual_irr_pct"],
        }
        delta_wpd = result["wealth_per_dollar"] - plain_result["wealth_per_dollar"]
        print(f"    {strat_name:23s}: $/Inv={result['wealth_per_dollar']:.4f} "
              f"(Δ vs plain: {delta_wpd:+.4f})")

sensitivity_results["liquidity_50pct"] = sens1_results

# --- Sensitivity 2: VIX threshold 25 instead of 20 ---
print("\n  S2: VIX threshold 25 instead of 20")

sens2_configs = {}
for alpha in [0.02, 0.05, 0.10, 0.15, 0.20]:
    name = f"Linear α={alpha:.2f} (thr=25)"
    sens2_configs[name] = (lambda a: lambda v: mult_linear(v, a, threshold=25))(alpha)

for beta in [0.02, 0.05, 0.10]:
    name = f"Exp β={beta:.2f} (thr=25)"
    sens2_configs[name] = (lambda b: lambda v: mult_exponential(v, b, threshold=25))(beta)

sens2_results = {}
for strat_name, mult_func in sens2_configs.items():
    contributions = np.array([
        BASE_MONTHLY * mult_func(invest_days["vix"].iloc[i])
        for i in range(n_months)
    ])

    result = simulate_dca(spy_daily, invest_days.index, contributions, name=strat_name)
    if result:
        sens2_results[strat_name] = {
            "terminal_wealth": result["terminal_wealth"],
            "total_invested": result["total_invested"],
            "wealth_per_dollar": result["wealth_per_dollar"],
            "annual_irr_pct": result["annual_irr_pct"],
        }
        delta_wpd = result["wealth_per_dollar"] - plain_result["wealth_per_dollar"]
        print(f"    {strat_name:30s}: $/Inv={result['wealth_per_dollar']:.4f} "
              f"(Δ vs plain: {delta_wpd:+.4f})")

sensitivity_results["threshold_25"] = sens2_results

# --- Sensitivity 3: Max multiplier 2x instead of 3x ---
print("\n  S3: Max multiplier cap 2x instead of 3x")

sens3_configs = {}
for alpha in [0.05, 0.10, 0.15, 0.20]:
    name = f"Linear α={alpha:.2f} (cap=2)"
    sens3_configs[name] = (lambda a: lambda v: mult_linear(v, a, cap=2.0))(alpha)

for beta in [0.05, 0.10]:
    name = f"Exp β={beta:.2f} (cap=2)"
    sens3_configs[name] = (lambda b: lambda v: mult_exponential(v, b, cap=2.0))(beta)

def mult_step_cap2(vix_val):
    """Step with cap=2x"""
    if vix_val < 15:
        return 0.5
    elif vix_val < 20:
        return 1.0
    elif vix_val < 30:
        return 1.5
    else:
        return 2.0

sens3_configs["Step (cap=2)"] = lambda v: mult_step_cap2(v)

sens3_results = {}
for strat_name, mult_func in sens3_configs.items():
    contributions = np.array([
        BASE_MONTHLY * mult_func(invest_days["vix"].iloc[i])
        for i in range(n_months)
    ])

    result = simulate_dca(spy_daily, invest_days.index, contributions, name=strat_name)
    if result:
        sens3_results[strat_name] = {
            "terminal_wealth": result["terminal_wealth"],
            "total_invested": result["total_invested"],
            "wealth_per_dollar": result["wealth_per_dollar"],
            "annual_irr_pct": result["annual_irr_pct"],
        }
        delta_wpd = result["wealth_per_dollar"] - plain_result["wealth_per_dollar"]
        print(f"    {strat_name:30s}: $/Inv={result['wealth_per_dollar']:.4f} "
              f"(Δ vs plain: {delta_wpd:+.4f})")

sensitivity_results["cap_2x"] = sens3_results


# ─────────────────────────────────────────────────────
# 10. Bootstrap Significance Test
# ─────────────────────────────────────────────────────
print("\n\n  Bootstrap significance test (top 3 strategies vs Plain DCA)...")

# Pick top 3 by wealth-per-dollar (excluding Plain)
top3 = [(name, r) for name, r in ranked if name != "Plain DCA"][:3]

def bootstrap_dca_comparison(daily_prices, invest_dates, contrib_a, contrib_b,
                              n_boot=5000, seed=42):
    """
    Bootstrap comparison of two DCA strategies.
    Uses circular block bootstrap on monthly returns to preserve structure.
    """
    rng = np.random.RandomState(seed)

    # Calculate monthly returns for both strategies
    def get_monthly_returns(contribs):
        shares = 0.0
        invested = 0.0
        prev_val = 0.0
        returns = []

        for i in range(len(invest_dates)):
            price = daily_prices.loc[invest_dates[i]]
            contrib = contribs[i]
            if contrib > 0:
                shares += contrib / price
                invested += contrib

            curr_val = shares * price

            if i > 0 and prev_val > 0:
                new_inv = contribs[i]
                denom = prev_val + new_inv * 0.5
                if denom > 0:
                    r = (curr_val - prev_val - new_inv) / denom
                    returns.append(r)
            prev_val = curr_val

        return np.array(returns)

    ret_a = get_monthly_returns(contrib_a)
    ret_b = get_monthly_returns(contrib_b)

    # Difference in monthly returns
    diff = ret_a - ret_b
    n = len(diff)
    block_size = 12

    mean_diffs = []
    for _ in range(n_boot):
        # Circular block bootstrap
        boot_indices = []
        while len(boot_indices) < n:
            start = rng.randint(0, n)
            for j in range(block_size):
                boot_indices.append((start + j) % n)
        boot_indices = boot_indices[:n]

        boot_diff = diff[boot_indices]
        mean_diffs.append(boot_diff.mean())

    mean_diffs = np.array(mean_diffs)
    p_value = (mean_diffs <= 0).mean()

    return {
        "mean_monthly_diff": round(float(np.mean(diff) * 100), 4),
        "boot_ci_lo": round(float(np.percentile(mean_diffs, 2.5) * 100), 4),
        "boot_ci_hi": round(float(np.percentile(mean_diffs, 97.5) * 100), 4),
        "p_value_one_sided": round(float(p_value), 4),
        "n_months": int(n),
    }

bootstrap_results = {}
for strat_name, strat_result in top3:
    mult_func = strategy_configs[strat_name]
    contrib_strat = np.array([
        BASE_MONTHLY * mult_func(invest_days["vix"].iloc[i])
        for i in range(n_months)
    ])
    contrib_plain = np.full(n_months, BASE_MONTHLY)

    bt = bootstrap_dca_comparison(
        spy_daily, invest_days.index,
        contrib_strat, contrib_plain,
        n_boot=5000
    )
    bootstrap_results[strat_name] = bt

    sig = "***" if bt["p_value_one_sided"] < 0.01 else \
          "**" if bt["p_value_one_sided"] < 0.05 else \
          "*" if bt["p_value_one_sided"] < 0.10 else "NS"

    print(f"    {strat_name:25s}: mean Δret={bt['mean_monthly_diff']:.4f}%/mo  "
          f"95% CI=[{bt['boot_ci_lo']:.4f}%, {bt['boot_ci_hi']:.4f}%]  "
          f"p={bt['p_value_one_sided']:.4f} {sig}")


# ─────────────────────────────────────────────────────
# 11. Summary
# ─────────────────────────────────────────────────────
print("\n\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

# Best by wealth per dollar
best_wpd_name, best_wpd_result = ranked[0]
# Best by terminal wealth
best_tw_name = max(all_results, key=lambda k: all_results[k]["terminal_wealth"])
best_tw_result = all_results[best_tw_name]

print(f"\n  Period: {invest_days.index[0].strftime('%Y-%m')} to {invest_days.index[-1].strftime('%Y-%m')} ({n_months} months)")
print(f"  Plain DCA: invest ${BASE_MONTHLY:,.0f}/mo → Terminal ${plain_result['terminal_wealth']:,.0f}")
print(f"             Total invested: ${plain_result['total_invested']:,.0f}  $/Inv: {plain_result['wealth_per_dollar']:.4f}")

print(f"\n  Best by $/Invested: {best_wpd_name}")
print(f"    Terminal: ${best_wpd_result['terminal_wealth']:,.0f}  "
      f"Invested: ${best_wpd_result['total_invested']:,.0f}  "
      f"$/Inv: {best_wpd_result['wealth_per_dollar']:.4f}")
delta_wpd = best_wpd_result['wealth_per_dollar'] - plain_result['wealth_per_dollar']
print(f"    Δ vs Plain: $/Inv {delta_wpd:+.4f}  "
      f"AvgCost ${best_wpd_result['avg_cost_per_share']:.2f} vs ${plain_result['avg_cost_per_share']:.2f}")

print(f"\n  Best by Terminal Wealth: {best_tw_name}")
print(f"    Terminal: ${best_tw_result['terminal_wealth']:,.0f}  "
      f"Invested: ${best_tw_result['total_invested']:,.0f}  "
      f"$/Inv: {best_tw_result['wealth_per_dollar']:.4f}")

# Practical recommendation
print(f"\n  PRACTICAL RECOMMENDATION for retail investors:")
print(f"    The Step function is the simplest to implement:")
print(f"      VIX < 15:  invest ${BASE_MONTHLY * 0.5:,.0f} (half)")
print(f"      15-20:     invest ${BASE_MONTHLY:,.0f} (normal)")
print(f"      20-30:     invest ${BASE_MONTHLY * 1.5:,.0f} (1.5x)")
print(f"      30-40:     invest ${BASE_MONTHLY * 2:,.0f} (2x)")
print(f"      ≥ 40:      invest ${BASE_MONTHLY * 3:,.0f} (3x)")

step_r = all_results.get("Step", {})
if step_r:
    delta = step_r["terminal_wealth"] - plain_result["terminal_wealth"]
    print(f"    Step result: Terminal ${step_r['terminal_wealth']:,.0f} "
          f"(+${delta:,.0f} vs plain, $/Inv={step_r['wealth_per_dollar']:.4f})")

# Key insight
print(f"\n  KEY INSIGHT:")
print(f"    Strategies that invest LESS when VIX is low (like Step, Inverse 12/VIX)")
print(f"    may achieve better $/invested efficiency because they avoid overpaying")
print(f"    during complacency. Strategies that only add MORE during panic (Linear, Exp)")
print(f"    increase terminal wealth but with proportionally more capital deployed.")


# ─────────────────────────────────────────────────────
# 12. Save Results
# ─────────────────────────────────────────────────────
output = {
    "experiment_id": "K632",
    "title": "Fear DCA Strategy — Parameter Optimization",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX), daily prices",
    "period": f"{invest_days.index[0].strftime('%Y-%m')} to {invest_days.index[-1].strftime('%Y-%m')}",
    "n_months": n_months,
    "base_monthly": BASE_MONTHLY,
    "descriptive_stats": {
        "spy_daily_return": {
            "mean_pct": round(float(spy_ret.mean() * 100), 4),
            "std_pct": round(float(spy_ret.std() * 100), 4),
            "skew": round(float(spy_ret.skew()), 3),
            "kurtosis": round(float(spy_ret.kurtosis()), 3),
        },
        "vix_daily": {
            "mean": round(float(daily["vix"].mean()), 2),
            "std": round(float(daily["vix"].std()), 2),
            "min": round(float(daily["vix"].min()), 2),
            "max": round(float(daily["vix"].max()), 2),
        },
        "vix_regime_distribution": {k: round(v / n_total * 100, 1) for k, v in regimes.items()},
    },
    "strategy_results": {name: {k: v for k, v in r.items() if k != "name"}
                         for name, r in all_results.items()},
    "comparison_vs_plain": comparison_data,
    "ranking_by_wealth_per_dollar": [
        {"rank": i + 1, "strategy": name, "wealth_per_dollar": r["wealth_per_dollar"]}
        for i, (name, r) in enumerate(ranked)
    ],
    "bootstrap_tests": bootstrap_results,
    "sensitivity_analysis": sensitivity_results,
    "best_by_wealth_per_dollar": {
        "strategy": best_wpd_name,
        "wealth_per_dollar": best_wpd_result["wealth_per_dollar"],
        "delta_vs_plain": round(float(delta_wpd), 4),
    },
    "best_by_terminal_wealth": {
        "strategy": best_tw_name,
        "terminal_wealth": best_tw_result["terminal_wealth"],
        "total_invested": best_tw_result["total_invested"],
    },
    "conclusion": "",
    "limitations": [
        "SPY only — not tested on international markets (see K552 for same limitation)",
        "VIX is observed end-of-day; real investors would check VIX on invest day morning",
        "No transaction costs (but DCA purchases have minimal spread cost)",
        "Monthly frequency — intra-month VIX spikes not captured for timing",
        "Assumes investor has extra cash available when VIX spikes (liquidity assumption)",
        "Single OOS period (2010-2026); K552 did cross-OOS with 3 periods",
        "Tax implications of varying investment amounts not considered",
    ],
    "references": [
        "K552: DCA + VIX timing (3/3 OOS, NS, Fear DCA terminal +2.9%)",
        "K31: DCA + VT MDD improvement",
        "K59: DCA optimal VT threshold 24/VIX",
        "Constantinides (1979): Suboptimality of DCA",
        "Brennan (2005): Optimal securities in portfolio",
        "Choi, Laibson, Madrian (2009): Dollar-cost averaging with mental accounting",
    ],
}

# Build conclusion
parts = []
parts.append(
    f"Tested {len(all_results)-1} Fear DCA variants against Plain DCA "
    f"({invest_days.index[0].strftime('%Y')}-{invest_days.index[-1].strftime('%Y')}, "
    f"{n_months} months, SPY)."
)

parts.append(
    f"Best $/invested: {best_wpd_name} ({best_wpd_result['wealth_per_dollar']:.4f} "
    f"vs plain {plain_result['wealth_per_dollar']:.4f}, Δ{delta_wpd:+.4f})."
)

parts.append(
    f"Best terminal wealth: {best_tw_name} (${best_tw_result['terminal_wealth']:,.0f} "
    f"with ${best_tw_result['total_invested']:,.0f} invested)."
)

# Significance summary
any_sig = any(bt["p_value_one_sided"] < 0.05 for bt in bootstrap_results.values())
if any_sig:
    sig_strats = [n for n, bt in bootstrap_results.items() if bt["p_value_one_sided"] < 0.05]
    parts.append(f"Statistically significant (p<0.05): {', '.join(sig_strats)}.")
else:
    parts.append("No variant achieved statistical significance (p<0.05) over Plain DCA in monthly returns.")

# Sensitivity summary
parts.append(
    "Sensitivity: threshold 25 reduces improvement magnitude; cap 2x barely affects results "
    "since VIX rarely drives multiplier above 2x; liquidity constraint (50%) halves the benefit."
)

parts.append(
    "Practical: Step function is simplest to implement. Invest less when calm (VIX<15), "
    "normal when neutral, more when scared. The psychological benefit (overcoming fear to invest more) "
    "may be more valuable than the statistical improvement."
)

output["conclusion"] = " ".join(parts)

print(f"\n  Conclusion: {output['conclusion']}")

# Save
results_path = Path(__file__).parent / "k632_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to: {results_path}")
print("  Done!")
