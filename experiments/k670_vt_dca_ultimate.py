#!/usr/bin/env python3
"""
K670: VT + Dollar Cost Averaging — The Ultimate Retail Strategy

Motivation:
  Most retail investors use DCA (monthly fixed investment). K632 optimized
  Fear DCA multipliers. K665 simplified VT to a 3-row lookup table. Can we
  combine these into THE ultimate simple strategy for someone investing
  $1000/month?

Design:
  Data: SPY, GLD, VIX daily via yfinance (2010-01-01 to 2026-03-27)
  Monthly DCA on first trading day of each month

  Strategies:
    a. Plain DCA: $1000 → SPY every month
    b. 60/40 DCA: $600 SPY + $400 GLD every month
    c. VIX Table DCA (K665 3-row): allocation varies by VIX, 50/50 SPY/GLD
    d. Fear DCA (K632): amount varies by VIX, all into SPY
    e. VIX Table + Fear DCA combined: both amount AND allocation vary
    f. Lump Sum: $192K at start (same total as ~192 months × $1000)

  Evaluation:
    - Terminal portfolio value
    - Total invested
    - Terminal value per dollar invested
    - IRR (internal rate of return)
    - Max drawdown of portfolio value
    - Simplicity score (1-5)

References:
  - K632: Fear DCA optimization (step multiplier best family)
  - K665: VIX lookup table simplification (3-row table)
  - K552: DCA + VIX timing (3/3 OOS consistent)
  - Constantinides (1979): Suboptimality of DCA
  - Brennan, Li, Torous (2005): Dollar cost averaging
  - Choi, Laibson, Madrian (2009): Mental accounting + DCA

Data source: yfinance (SPY, GLD, ^VIX), daily prices, monthly investing
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
print("K670: VT + Dollar Cost Averaging — The Ultimate Retail Strategy")
print("=" * 80)

print("\n[1/6] Downloading data...")
spy_raw = yf.download("SPY", start="2009-12-01", end="2026-03-28", progress=False)
gld_raw = yf.download("GLD", start="2009-12-01", end="2026-03-28", progress=False)
vix_raw = yf.download("^VIX", start="2009-12-01", end="2026-03-28", progress=False)

# Handle MultiIndex columns from newer yfinance
def extract_close(raw, ticker):
    if isinstance(raw.columns, pd.MultiIndex):
        return raw[("Close", ticker)]
    return raw["Close"]

spy_close = extract_close(spy_raw, "SPY")
gld_close = extract_close(gld_raw, "GLD")
vix_close = extract_close(vix_raw, "^VIX")

# Build daily DataFrame
daily = pd.DataFrame({
    "spy": spy_close,
    "gld": gld_close,
    "vix": vix_close
}).dropna()
daily.index = pd.to_datetime(daily.index)

print(f"  Daily data: {daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(daily)}")
print(f"  SPY range: ${daily['spy'].min():.2f} - ${daily['spy'].max():.2f}")
print(f"  GLD range: ${daily['gld'].min():.2f} - ${daily['gld'].max():.2f}")
print(f"  VIX range: {daily['vix'].min():.1f} - {daily['vix'].max():.1f} (mean {daily['vix'].mean():.1f})")

# ─────────────────────────────────────────────────────
# 2. Descriptive Statistics
# ─────────────────────────────────────────────────────
print("\n[2/6] Descriptive Statistics...")

spy_ret = daily["spy"].pct_change().dropna()
gld_ret = daily["gld"].pct_change().dropna()

print(f"  SPY daily return: mean={spy_ret.mean()*252*100:.2f}% ann, std={spy_ret.std()*np.sqrt(252)*100:.2f}% ann")
print(f"  GLD daily return: mean={gld_ret.mean()*252*100:.2f}% ann, std={gld_ret.std()*np.sqrt(252)*100:.2f}% ann")
print(f"  SPY-GLD correlation: {spy_ret.corr(gld_ret):.3f}")

# VIX regime distribution (monthly — on first trading day)
monthly_dates = daily.resample("MS").first().index
monthly_dates = [d for d in monthly_dates if d >= pd.Timestamp("2010-01-01")]
# Get first trading day of each month
first_td = []
for md in monthly_dates:
    mask = (daily.index.year == md.year) & (daily.index.month == md.month)
    sub = daily[mask]
    if len(sub) > 0:
        first_td.append(sub.index[0])

monthly_vix = daily.loc[first_td, "vix"]
n_months = len(monthly_vix)
print(f"\n  Monthly DCA period: {first_td[0].strftime('%Y-%m-%d')} to {first_td[-1].strftime('%Y-%m-%d')}")
print(f"  Total months: {n_months}")

# VIX regimes at investment dates
vix_lt15 = (monthly_vix < 15).sum()
vix_15_25 = ((monthly_vix >= 15) & (monthly_vix < 25)).sum()
vix_gt25 = (monthly_vix >= 25).sum()
print(f"  VIX < 15 (calm):  {vix_lt15} months ({vix_lt15/n_months*100:.1f}%)")
print(f"  VIX 15-25 (normal): {vix_15_25} months ({vix_15_25/n_months*100:.1f}%)")
print(f"  VIX > 25 (fear):  {vix_gt25} months ({vix_gt25/n_months*100:.1f}%)")

# Finer breakdown for Fear DCA
vix_lt15_f = (monthly_vix < 15).sum()
vix_15_20 = ((monthly_vix >= 15) & (monthly_vix < 20)).sum()
vix_20_30 = ((monthly_vix >= 20) & (monthly_vix < 30)).sum()
vix_30_40 = ((monthly_vix >= 30) & (monthly_vix < 40)).sum()
vix_ge40 = (monthly_vix >= 40).sum()
print(f"\n  Fear DCA regime breakdown:")
print(f"    VIX < 15:  {vix_lt15_f} ({vix_lt15_f/n_months*100:.1f}%) → $500")
print(f"    VIX 15-20: {vix_15_20} ({vix_15_20/n_months*100:.1f}%) → $1000")
print(f"    VIX 20-30: {vix_20_30} ({vix_20_30/n_months*100:.1f}%) → $1500")
print(f"    VIX 30-40: {vix_30_40} ({vix_30_40/n_months*100:.1f}%) → $2000")
print(f"    VIX ≥ 40:  {vix_ge40} ({vix_ge40/n_months*100:.1f}%) → $3000")

desc_stats = {
    "spy_annual_return_pct": round(spy_ret.mean() * 252 * 100, 2),
    "spy_annual_vol_pct": round(spy_ret.std() * np.sqrt(252) * 100, 2),
    "gld_annual_return_pct": round(gld_ret.mean() * 252 * 100, 2),
    "gld_annual_vol_pct": round(gld_ret.std() * np.sqrt(252) * 100, 2),
    "spy_gld_correlation": round(float(spy_ret.corr(gld_ret)), 3),
    "n_months": n_months,
    "vix_regime_at_invest_dates": {
        "VIX < 15": int(vix_lt15),
        "VIX 15-25": int(vix_15_25),
        "VIX > 25": int(vix_gt25),
    },
    "fear_dca_regime_months": {
        "VIX < 15 ($500)": int(vix_lt15_f),
        "VIX 15-20 ($1000)": int(vix_15_20),
        "VIX 20-30 ($1500)": int(vix_20_30),
        "VIX 30-40 ($2000)": int(vix_30_40),
        "VIX >= 40 ($3000)": int(vix_ge40),
    }
}


# ─────────────────────────────────────────────────────
# 3. DCA Simulation Engine
# ─────────────────────────────────────────────────────
print("\n[3/6] Running DCA simulations...")


def compute_irr(cashflows, dates):
    """Compute IRR using scipy brentq on NPV = 0."""
    if len(cashflows) < 2:
        return np.nan
    # Convert dates to years from first date
    t0 = dates[0]
    years = np.array([(d - t0).days / 365.25 for d in dates])

    def npv(r):
        return sum(cf / (1 + r) ** t for cf, t in zip(cashflows, years))

    try:
        return brentq(npv, -0.5, 5.0, maxiter=1000)
    except (ValueError, RuntimeError):
        return np.nan


def compute_max_drawdown(portfolio_values):
    """Max drawdown of portfolio value series."""
    values = np.array(portfolio_values)
    if len(values) < 2:
        return 0.0
    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak
    return float(dd.min())


def simulate_dca(daily_df, first_td_dates, strategy_func, strategy_name):
    """
    Simulate a monthly DCA strategy.

    strategy_func(vix, month_idx, cash_reserve) -> dict with:
      'invest_spy': dollars into SPY
      'invest_gld': dollars into GLD
      'to_cash': dollars to cash reserve
      'extra_from_cash': dollars taken from cash reserve to invest

    Returns dict of results.
    """
    spy_shares = 0.0
    gld_shares = 0.0
    cash_reserve = 0.0
    total_invested = 0.0  # money that actually entered the market
    total_contributed = 0.0  # money contributed by investor (incl. cash)

    # Track for IRR
    cashflows = []
    cf_dates = []

    # Track daily portfolio for MDD
    portfolio_values = []
    portfolio_dates = []

    for i, td in enumerate(first_td_dates):
        vix_val = daily_df.loc[td, "vix"]
        spy_price = daily_df.loc[td, "spy"]
        gld_price = daily_df.loc[td, "gld"]

        # Get strategy decision
        decision = strategy_func(vix_val, i, cash_reserve)

        invest_spy = decision["invest_spy"]
        invest_gld = decision["invest_gld"]
        to_cash = decision.get("to_cash", 0.0)
        from_cash = decision.get("extra_from_cash", 0.0)
        contribution = decision.get("contribution", 1000.0)

        # Update cash reserve
        cash_reserve += to_cash
        cash_reserve -= from_cash
        cash_reserve = max(cash_reserve, 0)

        # Buy shares
        if invest_spy > 0 and spy_price > 0:
            spy_shares += invest_spy / spy_price
        if invest_gld > 0 and gld_price > 0:
            gld_shares += invest_gld / gld_price

        total_invested += invest_spy + invest_gld
        total_contributed += contribution

        # IRR cashflow (negative = money out)
        cashflows.append(-contribution)
        cf_dates.append(td)

        # Track daily portfolio from this date to next invest date (or end)
        if i < len(first_td_dates) - 1:
            end_date = first_td_dates[i + 1]
        else:
            end_date = daily_df.index[-1]

        mask = (daily_df.index >= td) & (daily_df.index <= end_date)
        for d in daily_df[mask].index:
            pv = (spy_shares * daily_df.loc[d, "spy"] +
                  gld_shares * daily_df.loc[d, "gld"] +
                  cash_reserve)
            portfolio_values.append(pv)
            portfolio_dates.append(d)

    # Terminal value
    last_day = daily_df.index[-1]
    terminal = (spy_shares * daily_df.loc[last_day, "spy"] +
                gld_shares * daily_df.loc[last_day, "gld"] +
                cash_reserve)

    # Final cashflow for IRR (positive = money in from selling)
    cashflows.append(terminal)
    cf_dates.append(last_day)

    # IRR
    irr = compute_irr(cashflows, cf_dates)

    # Max drawdown
    mdd = compute_max_drawdown(portfolio_values)

    return {
        "strategy": strategy_name,
        "terminal_value": round(terminal, 2),
        "total_contributed": round(total_contributed, 2),
        "total_invested_in_market": round(total_invested, 2),
        "cash_reserve_final": round(cash_reserve, 2),
        "value_per_dollar_contributed": round(terminal / total_contributed, 4) if total_contributed > 0 else 0,
        "value_per_dollar_invested": round(terminal / total_invested, 4) if total_invested > 0 else 0,
        "irr_annual_pct": round(irr * 100, 3) if not np.isnan(irr) else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "spy_shares": round(spy_shares, 4),
        "gld_shares": round(gld_shares, 4),
        "portfolio_values": portfolio_values,
        "portfolio_dates": portfolio_dates,
    }


# ─────────────────────────────────────────────────────
# 4. Define Strategies
# ─────────────────────────────────────────────────────

# a. Plain DCA: $1000 → SPY every month
def plain_dca(vix, month_idx, cash_reserve):
    return {"invest_spy": 1000, "invest_gld": 0, "contribution": 1000}


# b. 60/40 DCA: $600 SPY + $400 GLD every month
def dca_60_40(vix, month_idx, cash_reserve):
    return {"invest_spy": 600, "invest_gld": 400, "contribution": 1000}


# c. VIX Table DCA (K665 3-row table)
#    VIX < 15: invest 100% ($1000), 50/50 SPY/GLD
#    VIX 15-25: invest 50% ($500), keep $500 cash; invested part 50/50
#    VIX > 25: invest 20% ($200), keep $800 cash; invested part 50/50
#    Cash accumulates and gets deployed next month if VIX drops
def vix_table_dca(vix, month_idx, cash_reserve):
    if vix < 15:
        # Invest all $1000 + any accumulated cash
        invest_total = 1000 + cash_reserve
        return {
            "invest_spy": invest_total * 0.5,
            "invest_gld": invest_total * 0.5,
            "to_cash": 0,
            "extra_from_cash": cash_reserve,
            "contribution": 1000,
        }
    elif vix < 25:
        return {
            "invest_spy": 250,
            "invest_gld": 250,
            "to_cash": 500,
            "extra_from_cash": 0,
            "contribution": 1000,
        }
    else:
        return {
            "invest_spy": 100,
            "invest_gld": 100,
            "to_cash": 800,
            "extra_from_cash": 0,
            "contribution": 1000,
        }


# d. Fear DCA (K632 step function)
#    VIX < 15: $500
#    VIX 15-20: $1000
#    VIX 20-30: $1500
#    VIX 30-40: $2000
#    VIX >= 40: $3000
#    All into SPY (as in K632)
def fear_dca(vix, month_idx, cash_reserve):
    if vix < 15:
        amt = 500
    elif vix < 20:
        amt = 1000
    elif vix < 30:
        amt = 1500
    elif vix < 40:
        amt = 2000
    else:
        amt = 3000
    return {"invest_spy": amt, "invest_gld": 0, "contribution": amt}


# e. VIX Table + Fear DCA combined
#    Amount from Fear DCA schedule
#    Allocation from VIX Table (50/50 SPY/GLD when invested)
#    Cash accumulation from VIX Table
def vix_table_fear_combined(vix, month_idx, cash_reserve):
    # Determine contribution amount (Fear DCA)
    if vix < 15:
        contribution = 500
    elif vix < 20:
        contribution = 1000
    elif vix < 30:
        contribution = 1500
    elif vix < 40:
        contribution = 2000
    else:
        contribution = 3000

    # Determine invest fraction (VIX Table)
    if vix < 15:
        invest_frac = 1.0
        # Also deploy accumulated cash
        invest_total = contribution + cash_reserve
        return {
            "invest_spy": invest_total * 0.5,
            "invest_gld": invest_total * 0.5,
            "to_cash": 0,
            "extra_from_cash": cash_reserve,
            "contribution": contribution,
        }
    elif vix < 25:
        invest_frac = 0.5
        invest_amt = contribution * invest_frac
        to_cash = contribution - invest_amt
        return {
            "invest_spy": invest_amt * 0.5,
            "invest_gld": invest_amt * 0.5,
            "to_cash": to_cash,
            "extra_from_cash": 0,
            "contribution": contribution,
        }
    else:
        invest_frac = 0.2
        invest_amt = contribution * invest_frac
        to_cash = contribution - invest_amt
        return {
            "invest_spy": invest_amt * 0.5,
            "invest_gld": invest_amt * 0.5,
            "to_cash": to_cash,
            "extra_from_cash": 0,
            "contribution": contribution,
        }


# f. Lump Sum at start
#    Invest equivalent of total Plain DCA contribution at day 1
#    We'll calculate total months first
total_lump = n_months * 1000  # Same total contribution


def lump_sum(vix, month_idx, cash_reserve):
    if month_idx == 0:
        # Invest everything on day 1, 50/50
        return {
            "invest_spy": total_lump * 0.5,
            "invest_gld": total_lump * 0.5,
            "contribution": total_lump,
        }
    else:
        return {"invest_spy": 0, "invest_gld": 0, "contribution": 0}


# ─────────────────────────────────────────────────────
# 5. Run All Strategies
# ─────────────────────────────────────────────────────

strategies = [
    ("a_plain_dca", "Plain DCA ($1k→SPY)", plain_dca, 1),
    ("b_60_40_dca", "60/40 DCA ($600 SPY + $400 GLD)", dca_60_40, 2),
    ("c_vix_table", "VIX Table DCA (K665)", vix_table_dca, 3),
    ("d_fear_dca", "Fear DCA (K632)", fear_dca, 4),
    ("e_combined", "VIX Table + Fear DCA", vix_table_fear_combined, 5),
    ("f_lump_sum", f"Lump Sum ${total_lump:,.0f}", lump_sum, 1),
]

results = {}
portfolio_series = {}

for key, name, func, simplicity in strategies:
    print(f"\n  Running: {name}...")
    res = simulate_dca(daily, first_td, func, name)
    res["simplicity_score"] = simplicity
    simplicity_labels = {1: "Trivial", 2: "Simple", 3: "Easy", 4: "Moderate", 5: "Complex"}
    res["simplicity_label"] = simplicity_labels.get(simplicity, "Unknown")

    # Store portfolio series separately (not in JSON)
    portfolio_series[key] = {
        "dates": res.pop("portfolio_dates"),
        "values": res.pop("portfolio_values"),
    }

    results[key] = res

    print(f"    Terminal: ${res['terminal_value']:>12,.2f} | "
          f"Contributed: ${res['total_contributed']:>10,.2f} | "
          f"$/$ contrib: {res['value_per_dollar_contributed']:.3f} | "
          f"IRR: {res['irr_annual_pct']:.1f}% | "
          f"MDD: {res['max_drawdown_pct']:.1f}%")

# ─────────────────────────────────────────────────────
# 6. Comparative Analysis + Practical Recommendation
# ─────────────────────────────────────────────────────
print("\n[4/6] Comparative Analysis...")
print("=" * 100)
print(f"{'Strategy':<35} {'Terminal':>12} {'Contributed':>12} {'$/$ Contr':>10} "
      f"{'$/$ Inv':>10} {'IRR%':>7} {'MDD%':>7} {'Simple':>7}")
print("-" * 100)

for key, name, func, simplicity in strategies:
    r = results[key]
    print(f"{r['strategy']:<35} ${r['terminal_value']:>11,.0f} ${r['total_contributed']:>11,.0f} "
          f"{r['value_per_dollar_contributed']:>10.3f} {r['value_per_dollar_invested']:>10.3f} "
          f"{r['irr_annual_pct']:>6.1f}% {r['max_drawdown_pct']:>6.1f}% "
          f"{r['simplicity_label']:>7}")

# Ranking by value per dollar contributed
print("\n\n[5/6] Rankings...")
ranked = sorted(results.items(), key=lambda x: x[1]["value_per_dollar_contributed"], reverse=True)
print("\n  By Value per Dollar Contributed (efficiency):")
for i, (k, r) in enumerate(ranked, 1):
    print(f"    {i}. {r['strategy']}: ${r['value_per_dollar_contributed']:.3f} per $1 contributed")

# Ranking by IRR
ranked_irr = sorted(results.items(),
                    key=lambda x: x[1]["irr_annual_pct"] if x[1]["irr_annual_pct"] else -999,
                    reverse=True)
print("\n  By IRR (return on money weighted by timing):")
for i, (k, r) in enumerate(ranked_irr, 1):
    irr_str = f"{r['irr_annual_pct']:.1f}%" if r['irr_annual_pct'] else "N/A"
    print(f"    {i}. {r['strategy']}: {irr_str}")

# Ranking by MDD (least negative = best)
ranked_mdd = sorted(results.items(), key=lambda x: x[1]["max_drawdown_pct"], reverse=True)
print("\n  By Max Drawdown (least severe):")
for i, (k, r) in enumerate(ranked_mdd, 1):
    print(f"    {i}. {r['strategy']}: {r['max_drawdown_pct']:.1f}%")

# ─────────────────────────────────────────────────────
# Practical Recommendation
# ─────────────────────────────────────────────────────
print("\n\n[6/6] PRACTICAL RECOMMENDATION")
print("=" * 80)

# Identify best DCA strategy (exclude lump sum)
dca_keys = [k for k in results if k != "f_lump_sum"]
best_irr_key = max(dca_keys, key=lambda k: results[k]["irr_annual_pct"] if results[k]["irr_annual_pct"] else -999)
best_eff_key = max(dca_keys, key=lambda k: results[k]["value_per_dollar_contributed"])
best_mdd_key = max(dca_keys, key=lambda k: results[k]["max_drawdown_pct"])

print(f"\n  Best IRR:        {results[best_irr_key]['strategy']} ({results[best_irr_key]['irr_annual_pct']:.1f}%)")
print(f"  Best Efficiency: {results[best_eff_key]['strategy']} (${results[best_eff_key]['value_per_dollar_contributed']:.3f}/$1)")
print(f"  Least MDD:       {results[best_mdd_key]['strategy']} ({results[best_mdd_key]['max_drawdown_pct']:.1f}%)")

# Practical table for retail investor
print("\n" + "=" * 80)
print("  IF YOU HAVE $1,000/MONTH — HERE'S WHAT TO DO:")
print("=" * 80)
print("""
  SIMPLEST (set and forget):
    → Plain DCA: Buy $1,000 of SPY on the 1st trading day. Done.
    → Complexity: ★☆☆☆☆

  BETTER (5 minutes/month):
    → 60/40 DCA: Buy $600 SPY + $400 GLD. Simple diversification.
    → Complexity: ★★☆☆☆

  SMART (check VIX once/month):
    → VIX Table DCA: Look up VIX on investing day, follow 3-row table:
      ┌──────────┬───────────────────────────────────────────┐
      │ VIX      │ Action                                    │
      ├──────────┼───────────────────────────────────────────┤
      │ < 15     │ Invest full $1,000 (50/50 SPY/GLD)       │
      │          │ + deploy any accumulated cash             │
      │ 15-25    │ Invest $500 (50/50), save $500 in cash   │
      │ > 25     │ Invest $200 (50/50), save $800 in cash   │
      └──────────┴───────────────────────────────────────────┘
    → Complexity: ★★★☆☆

  AGGRESSIVE (need extra cash reserves):
    → Fear DCA: Invest MORE when markets are scared:
      ┌──────────┬──────────┐
      │ VIX      │ Invest   │
      ├──────────┼──────────┤
      │ < 15     │ $500     │
      │ 15-20    │ $1,000   │
      │ 20-30    │ $1,500   │
      │ 30-40    │ $2,000   │
      │ ≥ 40     │ $3,000   │
      └──────────┴──────────┘
    → Complexity: ★★★★☆ (requires having extra cash available)
""")

# Vs Lump Sum note
ls = results["f_lump_sum"]
pd_res = results["a_plain_dca"]
print(f"  NOTE ON LUMP SUM:")
print(f"    Lump Sum ${total_lump:,.0f} (50/50 SPY/GLD) → ${ls['terminal_value']:,.0f}")
print(f"    Plain DCA $1k/mo × {n_months} months     → ${pd_res['terminal_value']:,.0f}")
if ls['terminal_value'] > pd_res['terminal_value']:
    pct_better = (ls['terminal_value'] / pd_res['terminal_value'] - 1) * 100
    print(f"    Lump Sum wins by {pct_better:.1f}% — consistent with academic literature")
    print(f"    BUT: Lump Sum MDD = {ls['max_drawdown_pct']:.1f}% vs DCA MDD = {pd_res['max_drawdown_pct']:.1f}%")
else:
    pct_better = (pd_res['terminal_value'] / ls['terminal_value'] - 1) * 100
    print(f"    DCA wins by {pct_better:.1f}% in this period")
print(f"    Most people don't HAVE ${total_lump:,.0f} upfront → DCA is the realistic path")


# ─────────────────────────────────────────────────────
# 7. Save Results
# ─────────────────────────────────────────────────────
print("\n\nSaving results...")

# Clean results for JSON
results_clean = {}
for k, v in results.items():
    results_clean[k] = {kk: vv for kk, vv in v.items()}

output = {
    "experiment_id": "K670",
    "title": "VT + Dollar Cost Averaging — The Ultimate Retail Strategy",
    "proposer": "Claude",
    "executor": "Claude",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX), daily prices",
    "data_period": f"{daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')}",
    "investment_period": f"{first_td[0].strftime('%Y-%m-%d')} to {first_td[-1].strftime('%Y-%m-%d')}",
    "n_months": n_months,
    "base_monthly": 1000.0,
    "descriptive_stats": desc_stats,
    "strategy_results": results_clean,
    "rankings": {
        "by_value_per_dollar_contributed": [
            {"rank": i + 1, "strategy": r["strategy"],
             "value_per_dollar": r["value_per_dollar_contributed"]}
            for i, (k, r) in enumerate(ranked)
        ],
        "by_irr": [
            {"rank": i + 1, "strategy": r["strategy"],
             "irr_pct": r["irr_annual_pct"]}
            for i, (k, r) in enumerate(ranked_irr)
        ],
        "by_max_drawdown": [
            {"rank": i + 1, "strategy": r["strategy"],
             "mdd_pct": r["max_drawdown_pct"]}
            for i, (k, r) in enumerate(ranked_mdd)
        ],
    },
    "practical_recommendation": {
        "simplest": {
            "strategy": "Plain DCA",
            "action": "Buy $1,000 of SPY on 1st trading day each month",
            "complexity": "1/5",
        },
        "better": {
            "strategy": "60/40 DCA",
            "action": "Buy $600 SPY + $400 GLD each month",
            "complexity": "2/5",
        },
        "smart": {
            "strategy": "VIX Table DCA",
            "action": "Check VIX, follow 3-row table for allocation",
            "complexity": "3/5",
            "table": [
                {"vix": "< 15", "action": "Invest full $1,000 (50/50 SPY/GLD) + accumulated cash"},
                {"vix": "15-25", "action": "Invest $500 (50/50), save $500 cash"},
                {"vix": "> 25", "action": "Invest $200 (50/50), save $800 cash"},
            ],
        },
        "aggressive": {
            "strategy": "Fear DCA",
            "action": "Invest more when VIX is high (requires extra cash)",
            "complexity": "4/5",
            "table": [
                {"vix": "< 15", "invest": "$500"},
                {"vix": "15-20", "invest": "$1,000"},
                {"vix": "20-30", "invest": "$1,500"},
                {"vix": "30-40", "invest": "$2,000"},
                {"vix": ">= 40", "invest": "$3,000"},
            ],
        },
    },
    "lump_sum_comparison": {
        "lump_sum_terminal": results["f_lump_sum"]["terminal_value"],
        "plain_dca_terminal": results["a_plain_dca"]["terminal_value"],
        "lump_sum_mdd": results["f_lump_sum"]["max_drawdown_pct"],
        "plain_dca_mdd": results["a_plain_dca"]["max_drawdown_pct"],
        "note": "Most retail investors don't have the lump sum upfront; DCA is realistic",
    },
    "references": [
        "K632: Fear DCA optimization (step multiplier best)",
        "K665: VIX lookup table simplification",
        "K552: DCA + VIX timing (3/3 OOS)",
        "Constantinides (1979): Suboptimality of DCA",
        "Brennan, Li, Torous (2005): Dollar cost averaging",
        "Choi, Laibson, Madrian (2009): Mental accounting + DCA",
    ],
}

# Save
out_path = Path(__file__).parent / "k670_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {out_path}")
print(f"\n{'=' * 80}")
print(f"  K670 COMPLETE — {n_months} months of DCA simulated across 6 strategies")
print(f"{'=' * 80}")
