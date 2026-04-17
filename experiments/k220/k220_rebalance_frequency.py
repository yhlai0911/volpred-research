"""
K220: Optimal Rebalance Frequency for 50/50 SPY/GLD — Transaction Cost Frontier
================================================================================
Background: K219 confirmed 50/50 is unbeatable. But what's the optimal rebalance
frequency? Monthly is the default, but is quarterly or even annual better after costs?

Data: SPY, GLD daily from yfinance. Full history.
OOS: 5-period cross-OOS 2015-2024 (each 2-year block).

Methodology:
  1. Test 8 rebalance frequencies: daily, weekly, bi-weekly, monthly,
     quarterly, semi-annual, annual, never (buy-and-hold drift)
  2. Each with 12/VIX VT overlay (monthly VT signal, rebalance portfolio at frequency)
  3. TX cost sensitivity: 0%, 0.05%, 0.1%, 0.2%, 0.5%
  4. For each frequency x TX cost: net Sharpe, MDD, turnover
  5. Find the "efficient frontier" of frequency vs TX cost
  6. Key question: at what TX cost does monthly become worse than quarterly?

Author: [提出: 用戶, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
from datetime import datetime

print("=" * 80)
print("K220: Optimal Rebalance Frequency for 50/50 SPY/GLD")
print("     Transaction Cost Frontier Analysis")
print("=" * 80)

# ============================================================
# 1. Download data
# ============================================================
print("\n[1/5] Downloading SPY, GLD, VIX data...")

spy_raw = yf.download("SPY", start="2004-01-01", end="2026-12-31", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-01-01", end="2026-12-31", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-01-01", end="2026-12-31", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

# Merge — GLD starts Nov 2004
data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data["gld_ret"] = np.log(data["gld_close"] / data["gld_close"].shift(1))
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ============================================================
# 2. Define 5-period Cross-OOS (2015-2024)
# ============================================================
print("\n[2/5] Setting up 5-period cross-OOS validation...")

OOS_PERIODS = [
    ("2015-01-01", "2016-12-31"),  # OOS1: post-taper, oil crash
    ("2017-01-01", "2018-12-31"),  # OOS2: low vol, vol explosion
    ("2019-01-01", "2020-12-31"),  # OOS3: COVID crash
    ("2021-01-01", "2022-12-31"),  # OOS4: inflation, rate hikes
    ("2023-01-01", "2024-12-31"),  # OOS5: recovery, AI rally
]

for i, (s, e) in enumerate(OOS_PERIODS):
    n = len(data.loc[s:e])
    print(f"  OOS{i+1}: {s} to {e} ({n} days)")

# ============================================================
# 3. Define rebalance frequencies and strategy logic
# ============================================================
print("\n[3/5] Defining rebalance frequencies...")

FREQUENCIES = [
    "daily",
    "weekly",       # every Friday
    "biweekly",     # every other Friday
    "monthly",      # 1st trading day of month
    "quarterly",    # 1st trading day of quarter
    "semiannual",   # 1st trading day of half-year
    "annual",       # 1st trading day of year
    "never",        # buy-and-hold drift
]

TX_COSTS = [0.0, 0.0005, 0.001, 0.002, 0.005]  # 0%, 5bp, 10bp, 20bp, 50bp

RF_DAILY = 0.04 / 252  # ~4% risk-free


def get_rebal_mask(dates: pd.DatetimeIndex, freq: str) -> np.ndarray:
    """Return boolean mask for rebalance days."""
    n = len(dates)
    mask = np.zeros(n, dtype=bool)

    if freq == "daily":
        mask[:] = True
    elif freq == "weekly":
        # Every Friday
        mask = dates.weekday == 4
        mask = np.array(mask)
    elif freq == "biweekly":
        # Every other Friday
        fridays = np.where(dates.weekday == 4)[0]
        for i in range(0, len(fridays), 2):
            mask[fridays[i]] = True
    elif freq == "monthly":
        # First trading day of each month
        months = dates.to_period("M")
        for m in months.unique():
            first_idx = np.where(months == m)[0][0]
            mask[first_idx] = True
    elif freq == "quarterly":
        # First trading day of each quarter
        quarters = dates.to_period("Q")
        for q in quarters.unique():
            first_idx = np.where(quarters == q)[0][0]
            mask[first_idx] = True
    elif freq == "semiannual":
        # First trading day of each half-year (Jan, Jul)
        for yr in sorted(set(dates.year)):
            for half_start_month in [1, 7]:
                candidates = np.where(
                    (dates.year == yr) & (dates.month >= half_start_month)
                )[0]
                if len(candidates) > 0:
                    # First day in this half
                    half_dates = dates[candidates]
                    half_months = half_dates.month
                    first_month_in_half = half_months.min()
                    first_day_candidates = np.where(
                        (dates.year == yr) & (dates.month == first_month_in_half)
                    )[0]
                    if len(first_day_candidates) > 0:
                        mask[first_day_candidates[0]] = True
    elif freq == "annual":
        # First trading day of each year
        for yr in sorted(set(dates.year)):
            yr_idx = np.where(dates.year == yr)[0]
            if len(yr_idx) > 0:
                mask[yr_idx[0]] = True
    elif freq == "never":
        # Only rebalance on day 0
        mask[0] = True

    # Always rebalance on day 0
    mask[0] = True
    return mask


def run_portfolio(spy_rets, gld_rets, vix_vals, dates, rebal_freq, tx_cost):
    """
    Run 50/50 SPY/GLD portfolio with 12/VIX VT overlay.

    VT signal: computed monthly from VIX (12/VIX scaling).
    Portfolio rebalance: at given frequency.
    At each rebalance:
      - Recompute VT weight from latest VIX
      - Rebalance to 50/50 SPY/GLD target
      - Pay TX cost on the total $ amount traded
    Between rebalances: weights drift with returns.
    """
    n = len(spy_rets)
    if n < 10:
        return None

    rebal_mask = get_rebal_mask(dates, rebal_freq)

    # Track portfolio value and allocations
    port_value = 1.0
    # Initial allocation
    vt_weight = min(12.0 / vix_vals[0], 1.5) if vix_vals[0] > 0 else 1.0
    vt_weight = max(vt_weight, 0.0)

    spy_alloc = port_value * 0.5 * vt_weight  # $ in SPY
    gld_alloc = port_value * 0.5 * vt_weight  # $ in GLD
    cash_alloc = port_value * (1.0 - vt_weight)  # $ in cash (earns rf)

    daily_returns = np.zeros(n)
    daily_turnover = np.zeros(n)
    weights_record = np.zeros(n)
    weights_record[0] = vt_weight

    for t in range(1, n):
        # Assets grow with returns
        spy_alloc *= np.exp(spy_rets[t])
        gld_alloc *= np.exp(gld_rets[t])
        cash_alloc *= np.exp(RF_DAILY)

        pre_cost_value = spy_alloc + gld_alloc + cash_alloc

        if rebal_mask[t]:
            # Compute new VT weight from current VIX
            new_vt = min(12.0 / vix_vals[t], 1.5) if vix_vals[t] > 0 else 1.0
            new_vt = max(new_vt, 0.0)

            # Target allocations (before cost)
            target_spy = pre_cost_value * 0.5 * new_vt
            target_gld = pre_cost_value * 0.5 * new_vt
            target_cash = pre_cost_value * (1.0 - new_vt)

            # Turnover = sum of absolute changes in $ allocation
            turnover = (abs(target_spy - spy_alloc) +
                        abs(target_gld - gld_alloc) +
                        abs(target_cash - cash_alloc))
            daily_turnover[t] = turnover / pre_cost_value  # as fraction of portfolio

            # Pay TX cost on amount traded
            cost = turnover * tx_cost
            post_cost_value = pre_cost_value - cost

            # Apply new allocations (after cost)
            spy_alloc = post_cost_value * 0.5 * new_vt
            gld_alloc = post_cost_value * 0.5 * new_vt
            cash_alloc = post_cost_value * (1.0 - new_vt)
            vt_weight = new_vt
        else:
            post_cost_value = pre_cost_value

        # Daily return includes both market return AND TX cost
        daily_returns[t] = np.log(post_cost_value / port_value)
        port_value = post_cost_value

        weights_record[t] = vt_weight

    return {
        "daily_returns": daily_returns,
        "turnover": daily_turnover,
        "weights": weights_record,
        "final_value": port_value,
    }


def compute_metrics(daily_rets, daily_turnover, n_days):
    """Compute performance metrics from daily return series."""
    years = n_days / 252

    ann_ret = np.mean(daily_rets) * 252
    ann_vol = np.std(daily_rets) * np.sqrt(252)
    sharpe = (np.mean(daily_rets) - RF_DAILY) / np.std(daily_rets) * np.sqrt(252) if np.std(daily_rets) > 0 else 0

    # Max drawdown
    cum = np.exp(np.cumsum(daily_rets))
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    max_dd = np.min(dd)

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    # Sortino
    down_rets = daily_rets[daily_rets < 0]
    down_vol = np.std(down_rets) * np.sqrt(252) if len(down_rets) > 0 else 1e-6
    sortino = (ann_ret - 0.04) / down_vol

    # Total turnover per year (one-way, as fraction)
    ann_turnover = np.sum(daily_turnover) / years

    # Number of rebalance events
    n_rebals = np.sum(daily_turnover > 0)

    return {
        "sharpe": round(sharpe, 4),
        "ann_ret": round(ann_ret, 5),
        "ann_vol": round(ann_vol, 5),
        "max_dd": round(max_dd, 5),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "ann_turnover": round(ann_turnover, 4),
        "n_rebals": int(n_rebals),
        "rebals_per_year": round(n_rebals / years, 1),
        "total_return": round(np.exp(np.sum(daily_rets)) - 1, 5),
    }


# ============================================================
# 4. Run all frequency x TX cost combinations across 5 OOS periods
# ============================================================
print("\n[4/5] Running experiments (8 frequencies x 5 TX costs x 5 OOS periods = 200 configs)...")

all_results = {}
# Also track full-sample results
full_results = {}

for freq in FREQUENCIES:
    all_results[freq] = {}
    full_results[freq] = {}
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"

        # Per-OOS results
        oos_metrics = []
        for oos_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
            subset = data.loc[oos_start:oos_end]
            if len(subset) < 30:
                continue
            result = run_portfolio(
                subset["spy_ret"].values,
                subset["gld_ret"].values,
                subset["vix_close"].values,
                subset.index,
                freq,
                tx,
            )
            if result is not None:
                metrics = compute_metrics(
                    result["daily_returns"],
                    result["turnover"],
                    len(subset),
                )
                metrics["oos_period"] = oos_idx + 1
                oos_metrics.append(metrics)

        # Aggregate across OOS periods
        if oos_metrics:
            avg_sharpe = np.mean([m["sharpe"] for m in oos_metrics])
            std_sharpe = np.std([m["sharpe"] for m in oos_metrics])
            avg_mdd = np.mean([m["max_dd"] for m in oos_metrics])
            avg_turnover = np.mean([m["ann_turnover"] for m in oos_metrics])
            avg_ret = np.mean([m["ann_ret"] for m in oos_metrics])

            # How many periods is this freq best?
            all_results[freq][tx_label] = {
                "avg_sharpe": round(avg_sharpe, 4),
                "std_sharpe": round(std_sharpe, 4),
                "avg_mdd": round(avg_mdd, 5),
                "avg_ann_ret": round(avg_ret, 5),
                "avg_ann_turnover": round(avg_turnover, 4),
                "per_oos": oos_metrics,
            }

        # Full sample 2015-2024 for reference
        full_subset = data.loc["2015-01-01":"2024-12-31"]
        if len(full_subset) > 100:
            result_full = run_portfolio(
                full_subset["spy_ret"].values,
                full_subset["gld_ret"].values,
                full_subset["vix_close"].values,
                full_subset.index,
                freq,
                tx,
            )
            if result_full is not None:
                full_metrics = compute_metrics(
                    result_full["daily_returns"],
                    result_full["turnover"],
                    len(full_subset),
                )
                full_results[freq][tx_label] = full_metrics

    print(f"  {freq:>12s} done.")

print("  All combinations computed.")

# ============================================================
# 5. Analysis and Output
# ============================================================
print("\n[5/5] Analysis")
print("=" * 80)

# --- Table 1: Cross-OOS Average Sharpe by Frequency x TX Cost ---
print("\n--- Table 1: Cross-OOS Average Sharpe (5 periods, 2015-2024) ---")
print(f"{'Frequency':<14}", end="")
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    print(f" {tx_label:>8}", end="")
print()
print("-" * (14 + 9 * len(TX_COSTS)))

for freq in FREQUENCIES:
    print(f"{freq:<14}", end="")
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in all_results[freq]:
            s = all_results[freq][tx_label]["avg_sharpe"]
            print(f" {s:>8.3f}", end="")
        else:
            print(f" {'N/A':>8}", end="")
    print()

# --- Table 2: Sharpe StdDev (consistency across OOS) ---
print("\n--- Table 2: Sharpe Std Dev across OOS (lower = more consistent) ---")
print(f"{'Frequency':<14}", end="")
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    print(f" {tx_label:>8}", end="")
print()
print("-" * (14 + 9 * len(TX_COSTS)))

for freq in FREQUENCIES:
    print(f"{freq:<14}", end="")
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in all_results[freq]:
            s = all_results[freq][tx_label]["std_sharpe"]
            print(f" {s:>8.3f}", end="")
        else:
            print(f" {'N/A':>8}", end="")
    print()

# --- Table 3: Average MDD by Frequency ---
print("\n--- Table 3: Cross-OOS Average MDD ---")
print(f"{'Frequency':<14}", end="")
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    print(f" {tx_label:>8}", end="")
print()
print("-" * (14 + 9 * len(TX_COSTS)))

for freq in FREQUENCIES:
    print(f"{freq:<14}", end="")
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in all_results[freq]:
            m = all_results[freq][tx_label]["avg_mdd"]
            print(f" {m:>7.1%}", end="")
        else:
            print(f" {'N/A':>8}", end="")
    print()

# --- Table 4: Annual Turnover (one-way, as fraction of portfolio) ---
print("\n--- Table 4: Average Annual Turnover (one-way, fraction of portfolio) ---")
print(f"{'Frequency':<14} {'Turnover':>10} {'Rebals/yr':>10}")
print("-" * 34)
for freq in FREQUENCIES:
    tx_label = "0bp"  # turnover is same regardless of cost
    if tx_label in all_results[freq]:
        t = all_results[freq][tx_label]["avg_ann_turnover"]
        r = np.mean([m["rebals_per_year"] for m in all_results[freq][tx_label]["per_oos"]])
        print(f"{freq:<14} {t:>9.1%} {r:>10.1f}")

# --- Table 5: Full-sample (2015-2024) Sharpe ---
print("\n--- Table 5: Full-Sample Sharpe (2015-2024, single period) ---")
print(f"{'Frequency':<14}", end="")
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    print(f" {tx_label:>8}", end="")
print()
print("-" * (14 + 9 * len(TX_COSTS)))

for freq in FREQUENCIES:
    print(f"{freq:<14}", end="")
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in full_results[freq]:
            s = full_results[freq][tx_label]["sharpe"]
            print(f" {s:>8.3f}", end="")
        else:
            print(f" {'N/A':>8}", end="")
    print()

# --- Key Analysis: Crossover Points ---
print("\n--- Key Analysis: At what TX cost does monthly lose to quarterly? ---")
print("-" * 80)

for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    monthly_s = all_results["monthly"].get(tx_label, {}).get("avg_sharpe", None)
    quarterly_s = all_results["quarterly"].get(tx_label, {}).get("avg_sharpe", None)
    if monthly_s is not None and quarterly_s is not None:
        diff = monthly_s - quarterly_s
        winner = "monthly" if diff > 0 else "quarterly"
        print(f"  TX={tx_label:>4s}: monthly={monthly_s:.4f}, quarterly={quarterly_s:.4f}, "
              f"diff={diff:+.4f} → {winner} wins")

# Find exact crossover point (interpolation)
print("\n--- Interpolated Crossover ---")
monthly_sharpes = []
quarterly_sharpes = []
tx_vals = []
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    ms = all_results["monthly"].get(tx_label, {}).get("avg_sharpe", None)
    qs = all_results["quarterly"].get(tx_label, {}).get("avg_sharpe", None)
    if ms is not None and qs is not None:
        monthly_sharpes.append(ms)
        quarterly_sharpes.append(qs)
        tx_vals.append(tx * 10000)  # in bps

monthly_sharpes = np.array(monthly_sharpes)
quarterly_sharpes = np.array(quarterly_sharpes)
tx_vals = np.array(tx_vals)
diff = monthly_sharpes - quarterly_sharpes

# Find zero crossing
crossover_found = False
for i in range(len(diff) - 1):
    if diff[i] * diff[i + 1] < 0:  # sign change
        # Linear interpolation
        x0, x1 = tx_vals[i], tx_vals[i + 1]
        y0, y1 = diff[i], diff[i + 1]
        crossover_bp = x0 - y0 * (x1 - x0) / (y1 - y0)
        print(f"  Monthly loses to quarterly at ~{crossover_bp:.1f} bps one-way TX cost")
        print(f"  (For US ETFs: typical 2-5 bps → monthly is {'likely fine' if crossover_bp > 5 else 'NOT optimal'})")
        crossover_found = True
        break

if not crossover_found:
    if all(d > 0 for d in diff):
        print("  Monthly ALWAYS beats quarterly across tested TX range (0-50 bps)")
    elif all(d <= 0 for d in diff):
        print("  Quarterly ALWAYS beats monthly across tested TX range (0-50 bps)")
    else:
        print("  No clean crossover found (non-monotonic relationship)")

# --- Rank all frequencies by Sharpe at each TX level ---
print("\n--- Frequency Rankings by Avg Sharpe ---")
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    freq_sharpes = []
    for freq in FREQUENCIES:
        s = all_results[freq].get(tx_label, {}).get("avg_sharpe", -999)
        freq_sharpes.append((freq, s))
    freq_sharpes.sort(key=lambda x: -x[1])
    rank_str = " > ".join(f"{f}({s:.3f})" for f, s in freq_sharpes if s > -999)
    print(f"  TX={tx_label:>4s}: {rank_str}")

# --- Per-OOS detail for monthly (the default) at 0 cost ---
print("\n--- Per-OOS Detail: Monthly rebalance, 0 TX cost ---")
print(f"{'OOS':>4s} {'Period':<22} {'Sharpe':>8} {'Return':>8} {'MDD':>8} {'Turnover':>10}")
print("-" * 60)
for m in all_results["monthly"]["0bp"]["per_oos"]:
    oos_s, oos_e = OOS_PERIODS[m["oos_period"] - 1]
    print(f"  {m['oos_period']:>2d}  {oos_s} to {oos_e}  {m['sharpe']:>7.3f} {m['ann_ret']:>7.1%} "
          f"{m['max_dd']:>7.1%} {m['ann_turnover']:>9.1%}")

# --- Efficient frontier: best frequency at each TX level ---
print("\n--- Efficient Frontier: Best Frequency at Each TX Level ---")
print(f"{'TX Cost':>10} {'Best Freq':<14} {'Sharpe':>8} {'MDD':>8} {'Turnover':>10}")
print("-" * 50)
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    best_freq = None
    best_sharpe = -999
    for freq in FREQUENCIES:
        s = all_results[freq].get(tx_label, {}).get("avg_sharpe", -999)
        if s > best_sharpe:
            best_sharpe = s
            best_freq = freq
    if best_freq:
        mdd = all_results[best_freq][tx_label]["avg_mdd"]
        to = all_results[best_freq][tx_label]["avg_ann_turnover"]
        print(f"  {tx_label:>6s}    {best_freq:<14} {best_sharpe:>7.3f} {mdd:>7.1%} {to:>9.1%}")

# --- Summary Verdict ---
print("\n" + "=" * 80)
print("SUMMARY VERDICT")
print("=" * 80)

# Compare monthly vs quarterly at typical retail cost (5-10 bps)
m5 = all_results["monthly"].get("5bp", {}).get("avg_sharpe", None)
q5 = all_results["quarterly"].get("5bp", {}).get("avg_sharpe", None)
m10 = all_results["monthly"].get("10bp", {}).get("avg_sharpe", None)
q10 = all_results["quarterly"].get("10bp", {}).get("avg_sharpe", None)

print(f"\nAt 5 bps (US ETFs typical):")
if m5 is not None and q5 is not None:
    print(f"  Monthly: {m5:.4f}  vs  Quarterly: {q5:.4f}  → {'Monthly' if m5 > q5 else 'Quarterly'} wins")
print(f"\nAt 10 bps (moderate cost):")
if m10 is not None and q10 is not None:
    print(f"  Monthly: {m10:.4f}  vs  Quarterly: {q10:.4f}  → {'Monthly' if m10 > q10 else 'Quarterly'} wins")

# Practical recommendation
best_zero = max(FREQUENCIES, key=lambda f: all_results[f].get("0bp", {}).get("avg_sharpe", -999))
best_10bp = max(FREQUENCIES, key=lambda f: all_results[f].get("10bp", {}).get("avg_sharpe", -999))
best_50bp = max(FREQUENCIES, key=lambda f: all_results[f].get("50bp", {}).get("avg_sharpe", -999))

print(f"\nBest frequency at 0 cost:   {best_zero}")
print(f"Best frequency at 10 bps:   {best_10bp}")
print(f"Best frequency at 50 bps:   {best_50bp}")

# Consistency check: std of Sharpe across OOS
m_std = all_results["monthly"].get("0bp", {}).get("std_sharpe", None)
q_std = all_results["quarterly"].get("0bp", {}).get("std_sharpe", None)
print(f"\nConsistency (Sharpe std across 5 OOS):")
if m_std is not None:
    print(f"  Monthly:   std={m_std:.3f}")
if q_std is not None:
    print(f"  Quarterly: std={q_std:.3f}")

print("\n" + "=" * 80)

# ============================================================
# 6. Save results JSON
# ============================================================
save_data = {
    "experiment": "K220",
    "title": "Optimal Rebalance Frequency for 50/50 SPY/GLD — TX Cost Frontier",
    "date": datetime.now().isoformat(),
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "oos_periods": OOS_PERIODS,
    "frequencies": FREQUENCIES,
    "tx_costs_bps": [tx * 10000 for tx in TX_COSTS],
    "cross_oos_results": {},
    "full_sample_results": {},
    "efficient_frontier": {},
}

# Store cross-OOS averages (without per_oos detail to keep JSON manageable)
for freq in FREQUENCIES:
    save_data["cross_oos_results"][freq] = {}
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in all_results[freq]:
            entry = dict(all_results[freq][tx_label])
            # Convert per_oos to summary
            entry["per_oos_sharpes"] = [m["sharpe"] for m in entry.pop("per_oos")]
            save_data["cross_oos_results"][freq][tx_label] = entry

# Store full-sample results
for freq in FREQUENCIES:
    save_data["full_sample_results"][freq] = {}
    for tx in TX_COSTS:
        tx_label = f"{tx*10000:.0f}bp"
        if tx_label in full_results[freq]:
            save_data["full_sample_results"][freq][tx_label] = full_results[freq][tx_label]

# Efficient frontier
for tx in TX_COSTS:
    tx_label = f"{tx*10000:.0f}bp"
    best_freq = max(FREQUENCIES, key=lambda f: all_results[f].get(tx_label, {}).get("avg_sharpe", -999))
    save_data["efficient_frontier"][tx_label] = {
        "best_frequency": best_freq,
        "sharpe": all_results[best_freq][tx_label]["avg_sharpe"],
        "mdd": all_results[best_freq][tx_label]["avg_mdd"],
        "turnover": all_results[best_freq][tx_label]["avg_ann_turnover"],
    }

out_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a27b2abd/experiments/k220_rebalance_frequency_results.json"
with open(out_path, "w") as f:
    json.dump(save_data, f, indent=2)
print(f"\nResults saved to {out_path}")
print("K220 complete.")
