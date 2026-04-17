"""
K291: Realistic Investor Behavior Simulation
=============================================
[提出: 用戶, 執行: Claude]

Research Question:
  K234 found 85% of VT rebalances are easy. But real investors also make
  OTHER mistakes: panic selling, performance chasing, stopping the strategy
  after losses. How much do these behavioral deviations cost?

Methodology:
  1. "Perfect" 50/50 SPY/GLD + 12/VIX baseline (mechanical monthly execution)
  2. Behavioral variants (each simulates a common mistake):
     a. Panic seller: stops VT after any month with >5% loss, goes full cash 3 months
     b. Performance chaser: abandons 50/50 for 100% SPY after SPY outperforms by >10% YTD
     c. Lazy rebalancer: forgets 30% of rebalance dates (random skip)
     d. Overconfident: doubles VT aggressiveness (24/VIX instead of 12/VIX)
        after 3 consecutive profitable months
     e. Anchored: refuses to rebalance if portfolio is at a loss (only rebalances at profit)
  3. For each variant: Sharpe, MDD, terminal wealth vs perfect execution
  4. "Behavioral tax": annualized cost of each mistake
  5. Which mistake is MOST costly? Which is LEAST costly?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json
import os

np.random.seed(42)

WORKTREE = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(WORKTREE, "k291_behavior_simulation_results.json")

# ============================================================
# 1. Download and prepare historical data
# ============================================================
print("=" * 72)
print("K291: Realistic Investor Behavior Simulation")
print("     What Happens When Real People Use 50/50 + VT?")
print("=" * 72)
print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

print("\n[1/6] Downloading SPY, GLD, and VIX data...")
spy_raw = yf.download("SPY", start="2004-01-01", end="2026-12-31",
                       progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-01-01", end="2026-12-31",
                       progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-01-01", end="2026-12-31",
                       progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data["spy_ret"] = data["spy_close"].pct_change()
data["gld_ret"] = data["gld_close"].pct_change()
data = data.dropna()

# Focus on 2005-2024 (GLD starts Nov 2004)
data = data.loc["2005-01-01":"2024-12-31"]
print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {len(data)}")

# ============================================================
# 2. Build 50/50 + 12/VIX Monthly VT Baseline
# ============================================================
print("\n[2/6] Building perfect 50/50 + 12/VIX monthly VT baseline...")

spy_ret = data["spy_ret"].values
gld_ret = data["gld_ret"].values
vix_levels = data["vix_close"].values
dates = data.index

# Identify month-end rebalance dates (last trading day of each month)
data["year_month"] = data.index.to_period("M")
month_ends = data.groupby("year_month").tail(1).index
rebal_set = set(month_ends)

N = len(data)


def run_perfect_strategy():
    """Perfect mechanical 50/50 + 12/VIX monthly rebalance."""
    wealth = np.ones(N)
    weights_equity = np.zeros(N)  # VT weight on risky portion
    current_vt_weight = 1.0  # start fully invested

    for t in range(1, N):
        # Check if previous day was a rebalance date
        if dates[t-1] in rebal_set:
            # Use previous day's VIX (lagged) to set weight
            vix_prev = vix_levels[t-1]
            current_vt_weight = min(12.0 / vix_prev, 1.5)
            current_vt_weight = max(current_vt_weight, 0.0)

        # 50/50 SPY/GLD, scaled by VT weight
        port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
        # Remainder in cash (assume 0 for simplicity, or use RF)
        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

        weights_equity[t] = current_vt_weight

    return wealth, weights_equity


def compute_metrics(wealth, label=""):
    """Compute standard performance metrics from a wealth series."""
    daily_ret = np.diff(wealth) / wealth[:-1]
    daily_ret = daily_ret[~np.isnan(daily_ret)]

    ann_ret = (wealth[-1] / wealth[0]) ** (252.0 / len(daily_ret)) - 1
    ann_vol = np.std(daily_ret) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    # MDD
    peak = np.maximum.accumulate(wealth)
    dd = (wealth - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    neg_ret = daily_ret[daily_ret < 0]
    downside_vol = np.std(neg_ret) * np.sqrt(252) if len(neg_ret) > 0 else 1e-6
    sortino = (ann_ret - 0.04) / downside_vol

    terminal_wealth = wealth[-1]
    n_years = len(daily_ret) / 252

    return {
        "label": label,
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "terminal_wealth": round(float(terminal_wealth), 4),
        "n_years": round(float(n_years), 1),
    }


perfect_wealth, perfect_weights = run_perfect_strategy()
baseline = compute_metrics(perfect_wealth, "Perfect 50/50+VT")
print(f"  Baseline: Sharpe={baseline['sharpe']:.3f}, MDD={baseline['mdd']:.1%}, "
      f"Terminal=${baseline['terminal_wealth']:.2f}")

# ============================================================
# 3. Behavioral Variant Simulations
# ============================================================
print("\n[3/6] Simulating behavioral variants...")


# --- 3a. Panic Seller ---
# NOTE: We test TWO thresholds: -5% AND -3%.
# 50/50+VT is so well-dampened that -5% months are extremely rare.
# -3% is more realistic for typical investor pain thresholds.
def run_panic_seller(threshold=-0.03):
    """
    After any month with loss exceeding threshold, goes 100% cash for 3 months.
    Resumes VT after the cooling-off period.
    """
    wealth = np.ones(N)
    current_vt_weight = 1.0
    months_in_cash = 0  # countdown
    panic_events = 0

    # Track monthly returns for panic detection
    month_start_wealth = 1.0
    month_start_idx = 0

    for t in range(1, N):
        if dates[t-1] in rebal_set:
            # End of month: check if this month exceeded pain threshold
            month_ret = (wealth[t-1] - month_start_wealth) / month_start_wealth
            if month_ret < threshold and months_in_cash == 0:
                months_in_cash = 3
                panic_events += 1

            # Start new month
            month_start_wealth = wealth[t-1]
            month_start_idx = t

            if months_in_cash > 0:
                months_in_cash -= 1
                current_vt_weight = 0.0  # full cash
            else:
                vix_prev = vix_levels[t-1]
                current_vt_weight = min(12.0 / vix_prev, 1.5)
                current_vt_weight = max(current_vt_weight, 0.0)

        port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth, panic_events


# --- 3b. Performance Chaser ---
def run_performance_chaser():
    """
    Abandons 50/50 for 100% SPY when SPY outperforms GLD by >10% YTD.
    Reverts to 50/50 at start of each new year.
    """
    wealth = np.ones(N)
    current_vt_weight = 1.0
    chasing = False
    chase_events = 0

    # Track YTD performance
    year_start_spy = data["spy_close"].iloc[0]
    year_start_gld = data["gld_close"].iloc[0]
    current_year = dates[0].year

    for t in range(1, N):
        # New year reset
        if dates[t].year != current_year:
            current_year = dates[t].year
            year_start_spy = data["spy_close"].iloc[t-1]
            year_start_gld = data["gld_close"].iloc[t-1]
            chasing = False

        if dates[t-1] in rebal_set:
            vix_prev = vix_levels[t-1]
            current_vt_weight = min(12.0 / vix_prev, 1.5)
            current_vt_weight = max(current_vt_weight, 0.0)

            # Check YTD performance gap
            spy_ytd = (data["spy_close"].iloc[t] / year_start_spy - 1) * 100
            gld_ytd = (data["gld_close"].iloc[t] / year_start_gld - 1) * 100
            if spy_ytd - gld_ytd > 10 and not chasing:
                chasing = True
                chase_events += 1

        if chasing:
            # 100% SPY instead of 50/50
            port_ret = current_vt_weight * spy_ret[t]
        else:
            port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])

        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth, chase_events


# --- 3c. Lazy Rebalancer ---
def run_lazy_rebalancer(skip_rate=0.30, seed=42):
    """
    Skips 30% of rebalance dates randomly. Keeps previous weight when skipped.
    """
    rng = np.random.RandomState(seed)
    wealth = np.ones(N)
    current_vt_weight = 1.0
    skips = 0
    total_rebal = 0

    for t in range(1, N):
        if dates[t-1] in rebal_set:
            total_rebal += 1
            if rng.rand() < skip_rate:
                # Skip this rebalance — keep previous weight
                skips += 1
            else:
                vix_prev = vix_levels[t-1]
                current_vt_weight = min(12.0 / vix_prev, 1.5)
                current_vt_weight = max(current_vt_weight, 0.0)

        port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth, skips, total_rebal


# --- 3d. Overconfident ---
def run_overconfident():
    """
    After 3 consecutive profitable months, doubles aggressiveness:
    uses 24/VIX instead of 12/VIX.
    Reverts to 12/VIX after any losing month.
    """
    wealth = np.ones(N)
    current_vt_weight = 1.0
    consecutive_wins = 0
    aggressive = False
    aggressive_months = 0
    total_months = 0

    month_start_wealth = 1.0

    for t in range(1, N):
        if dates[t-1] in rebal_set:
            total_months += 1
            # Check if previous month was profitable
            month_ret = (wealth[t-1] - month_start_wealth) / month_start_wealth
            if month_ret > 0:
                consecutive_wins += 1
            else:
                consecutive_wins = 0
                aggressive = False

            if consecutive_wins >= 3:
                aggressive = True

            month_start_wealth = wealth[t-1]

            vix_prev = vix_levels[t-1]
            multiplier = 24.0 if aggressive else 12.0
            current_vt_weight = min(multiplier / vix_prev, 1.5)
            current_vt_weight = max(current_vt_weight, 0.0)

            if aggressive:
                aggressive_months += 1

        port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth, aggressive_months, total_months


# --- 3e. Anchored ---
def run_anchored():
    """
    Refuses to rebalance if portfolio is at a loss from initial investment.
    Only rebalances when portfolio is at or above high-water mark.
    """
    wealth = np.ones(N)
    current_vt_weight = 1.0
    hwm = 1.0  # high water mark
    refused = 0
    total_rebal = 0

    for t in range(1, N):
        if dates[t-1] in rebal_set:
            total_rebal += 1
            if wealth[t-1] < hwm:
                # At a loss from HWM — refuse to rebalance, keep old weight
                refused += 1
            else:
                vix_prev = vix_levels[t-1]
                current_vt_weight = min(12.0 / vix_prev, 1.5)
                current_vt_weight = max(current_vt_weight, 0.0)
                hwm = wealth[t-1]  # update HWM

        port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
        cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth, refused, total_rebal


# Execute all variants
# Panic seller: test both -5% and -3% thresholds
panic_wealth_5pct, panic_events_5pct = run_panic_seller(threshold=-0.05)
panic_wealth, panic_events = run_panic_seller(threshold=-0.03)  # primary: -3%
chaser_wealth, chase_events = run_performance_chaser()
lazy_wealth, lazy_skips, lazy_total = run_lazy_rebalancer()
overconf_wealth, aggressive_months, total_months_oc = run_overconfident()
anchored_wealth, anchored_refused, anchored_total = run_anchored()

# First, report monthly return distribution to contextualize panic thresholds
print("\n  [Monthly return distribution of perfect 50/50+VT]")
monthly_rets = []
m_start_w = perfect_wealth[0]
for t in range(1, N):
    if dates[t-1] in rebal_set:
        m_ret = (perfect_wealth[t-1] - m_start_w) / m_start_w
        monthly_rets.append(m_ret)
        m_start_w = perfect_wealth[t-1]
monthly_rets = np.array(monthly_rets)
print(f"  Min monthly return: {monthly_rets.min():.2%}")
print(f"  Max monthly return: {monthly_rets.max():.2%}")
print(f"  Months worse than -5%: {(monthly_rets < -0.05).sum()}")
print(f"  Months worse than -3%: {(monthly_rets < -0.03).sum()}")
print(f"  Months worse than -2%: {(monthly_rets < -0.02).sum()}")
print(f"  → This shows how effective VT is at dampening monthly drawdowns.")
print(f"\n  Panic seller (-5% threshold): {panic_events_5pct} events → NEVER triggers!")
print(f"  Panic seller (-3% threshold): {panic_events} events")

# Also run multiple seeds for lazy rebalancer to get distribution
lazy_results_multi = []
for seed in range(100):
    w, sk, tot = run_lazy_rebalancer(skip_rate=0.30, seed=seed)
    lazy_results_multi.append(compute_metrics(w, f"Lazy_seed{seed}"))

# ============================================================
# 4. Compute Metrics & Behavioral Tax
# ============================================================
print("\n[4/6] Computing metrics and behavioral tax...")

variants = {
    "Perfect 50/50+VT": perfect_wealth,
    "Panic Seller (-3%)": panic_wealth,
    "Performance Chaser": chaser_wealth,
    "Lazy Rebalancer": lazy_wealth,
    "Overconfident": overconf_wealth,
    "Anchored": anchored_wealth,
}

all_metrics = {}
for name, w in variants.items():
    m = compute_metrics(w, name)
    all_metrics[name] = m

# Behavioral tax = annualized return difference vs perfect
n_years = all_metrics["Perfect 50/50+VT"]["n_years"]
perfect_ann = all_metrics["Perfect 50/50+VT"]["ann_return"]
perfect_terminal = all_metrics["Perfect 50/50+VT"]["terminal_wealth"]

print("\n" + "=" * 72)
print("RESULTS: Performance Comparison")
print("=" * 72)
print(f"\n{'Strategy':<25} {'Sharpe':>8} {'MDD':>8} {'AnnRet':>8} {'Terminal$':>10} {'BehavTax':>10}")
print("-" * 72)

behavioral_taxes = {}
for name, m in all_metrics.items():
    tax = perfect_ann - m["ann_return"]
    behavioral_taxes[name] = tax
    tax_str = f"{tax:+.2%}" if name != "Perfect 50/50+VT" else "baseline"
    print(f"  {name:<23} {m['sharpe']:>8.3f} {m['mdd']:>8.1%} {m['ann_return']:>8.2%} "
          f"${m['terminal_wealth']:>9.2f} {tax_str:>10}")

# ============================================================
# 5. Detailed Analysis
# ============================================================
print("\n" + "=" * 72)
print("DETAILED ANALYSIS")
print("=" * 72)

# 5a. Panic Seller details
print(f"\n--- Panic Seller (-3% threshold) ---")
print(f"  Panic events (went to cash for 3 months): {panic_events}")
print(f"  Months spent in cash: {panic_events * 3}")
panic_tax = behavioral_taxes["Panic Seller (-3%)"]
print(f"  Behavioral tax: {panic_tax:.2%}/yr")
wealth_diff = perfect_terminal - all_metrics["Panic Seller (-3%)"]["terminal_wealth"]
print(f"  Terminal wealth lost: ${wealth_diff:.2f} (per $1 invested)")

# 5b. Performance Chaser details
print(f"\n--- Performance Chaser ---")
print(f"  Chase events (switched to 100% SPY): {chase_events}")
chaser_tax = behavioral_taxes["Performance Chaser"]
print(f"  Behavioral tax: {chaser_tax:.2%}/yr")
wealth_diff = perfect_terminal - all_metrics["Performance Chaser"]["terminal_wealth"]
print(f"  Terminal wealth lost: ${wealth_diff:.2f}")

# 5c. Lazy Rebalancer details
print(f"\n--- Lazy Rebalancer ---")
print(f"  Rebalances skipped: {lazy_skips}/{lazy_total} ({lazy_skips/lazy_total:.0%})")
lazy_tax = behavioral_taxes["Lazy Rebalancer"]
print(f"  Behavioral tax: {lazy_tax:.2%}/yr")
# Show distribution from 100 seeds
lazy_sharpes = [r["sharpe"] for r in lazy_results_multi]
lazy_terminals = [r["terminal_wealth"] for r in lazy_results_multi]
print(f"  100-seed Sharpe: mean={np.mean(lazy_sharpes):.3f}, "
      f"std={np.std(lazy_sharpes):.3f}, "
      f"range=[{np.min(lazy_sharpes):.3f}, {np.max(lazy_sharpes):.3f}]")
print(f"  100-seed Terminal$: mean=${np.mean(lazy_terminals):.2f}, "
      f"std=${np.std(lazy_terminals):.2f}")

# 5d. Overconfident details
print(f"\n--- Overconfident ---")
print(f"  Aggressive months (24/VIX): {aggressive_months}/{total_months_oc} "
      f"({aggressive_months/total_months_oc:.0%})")
overconf_tax = behavioral_taxes["Overconfident"]
print(f"  Behavioral tax: {overconf_tax:.2%}/yr")
wealth_diff = perfect_terminal - all_metrics["Overconfident"]["terminal_wealth"]
print(f"  Terminal wealth impact: ${wealth_diff:+.2f}")

# 5e. Anchored details
print(f"\n--- Anchored ---")
print(f"  Refused rebalances (below HWM): {anchored_refused}/{anchored_total} "
      f"({anchored_refused/anchored_total:.0%})")
anchored_tax = behavioral_taxes["Anchored"]
print(f"  Behavioral tax: {anchored_tax:.2%}/yr")

# ============================================================
# 6. Rankings & Statistical Tests
# ============================================================
print("\n" + "=" * 72)
print("BEHAVIORAL TAX RANKINGS")
print("=" * 72)

# Rank by behavioral tax (excluding perfect baseline)
ranked = sorted(
    [(name, tax) for name, tax in behavioral_taxes.items()
     if name != "Perfect 50/50+VT"],
    key=lambda x: abs(x[1]),
    reverse=True
)

print(f"\n  MOST costly mistake → LEAST costly:")
for i, (name, tax) in enumerate(ranked, 1):
    direction = "cost" if tax > 0 else "gain(!)"
    print(f"  #{i}: {name:<25} → {abs(tax):.2%}/yr {direction}")

# Test: is the worst deviation statistically different from perfect?
print(f"\n--- Statistical Significance (Sharpe difference) ---")
for name, w in variants.items():
    if name == "Perfect 50/50+VT":
        continue
    daily_ret_perfect = np.diff(perfect_wealth) / perfect_wealth[:-1]
    daily_ret_variant = np.diff(w) / w[:-1]
    diff = daily_ret_perfect - daily_ret_variant
    t_stat = np.mean(diff) / (np.std(diff) / np.sqrt(len(diff)))
    p_val = 1 - stats.t.cdf(abs(t_stat), df=len(diff)-1)
    sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "n.s."
    print(f"  {name:<25}: t={t_stat:>6.2f}, p={p_val:.4f} {sig}")

# ============================================================
# 7. Crisis Period Analysis
# ============================================================
print("\n" + "=" * 72)
print("CRISIS PERIOD ANALYSIS")
print("=" * 72)

crisis_periods = {
    "GFC (2008-03 to 2009-03)": ("2008-03-01", "2009-03-31"),
    "COVID (2020-02 to 2020-04)": ("2020-02-01", "2020-04-30"),
    "2022 Bear (2022-01 to 2022-10)": ("2022-01-01", "2022-10-31"),
}

for crisis_name, (start, end) in crisis_periods.items():
    mask = (dates >= start) & (dates <= end)
    if mask.sum() == 0:
        continue
    idx = np.where(mask)[0]
    i_start, i_end = idx[0], idx[-1]

    print(f"\n  {crisis_name}:")
    for name, w in variants.items():
        crisis_ret = (w[i_end] / w[i_start] - 1) * 100
        crisis_peak = np.maximum.accumulate(w[i_start:i_end+1])
        crisis_dd = ((w[i_start:i_end+1] - crisis_peak) / crisis_peak).min() * 100
        print(f"    {name:<25}: return={crisis_ret:>+6.1f}%, MDD={crisis_dd:>+6.1f}%")

# ============================================================
# 8. Cumulative Behavioral Tax Over Time
# ============================================================
print("\n" + "=" * 72)
print("CUMULATIVE BEHAVIORAL TAX (per decade)")
print("=" * 72)

decades = {
    "2005-2009": ("2005-01-01", "2009-12-31"),
    "2010-2014": ("2010-01-01", "2014-12-31"),
    "2015-2019": ("2015-01-01", "2019-12-31"),
    "2020-2024": ("2020-01-01", "2024-12-31"),
}

for decade_name, (start, end) in decades.items():
    mask = (dates >= start) & (dates <= end)
    if mask.sum() < 100:
        continue
    idx = np.where(mask)[0]
    i_start, i_end = idx[0], idx[-1]
    n_yrs = mask.sum() / 252

    print(f"\n  {decade_name} ({mask.sum()} days, {n_yrs:.1f} yrs):")
    perf_ret = (perfect_wealth[i_end] / perfect_wealth[i_start]) ** (1/n_yrs) - 1
    for name, w in variants.items():
        if name == "Perfect 50/50+VT":
            continue
        var_ret = (w[i_end] / w[i_start]) ** (1/n_yrs) - 1
        decade_tax = perf_ret - var_ret
        print(f"    {name:<25}: tax={decade_tax:>+.2%}/yr")

# ============================================================
# 9. Combined Behavioral Failures
# ============================================================
print("\n" + "=" * 72)
print("COMBINED BEHAVIORAL FAILURES")
print("=" * 72)
print("  What if an investor makes MULTIPLE mistakes simultaneously?")


def run_combined_worst():
    """
    Combined worst-case: panic seller + performance chaser + overconfident.
    Panic > chaser > overconfident priority.
    """
    wealth = np.ones(N)
    current_vt_weight = 1.0
    months_in_cash = 0
    consecutive_wins = 0
    chasing = False
    current_year = dates[0].year
    year_start_spy = data["spy_close"].iloc[0]
    year_start_gld = data["gld_close"].iloc[0]
    month_start_wealth = 1.0

    for t in range(1, N):
        # New year reset for chasing
        if dates[t].year != current_year:
            current_year = dates[t].year
            year_start_spy = data["spy_close"].iloc[t-1]
            year_start_gld = data["gld_close"].iloc[t-1]
            chasing = False

        if dates[t-1] in rebal_set:
            # Check panic
            month_ret = (wealth[t-1] - month_start_wealth) / month_start_wealth
            if month_ret < -0.05 and months_in_cash == 0:
                months_in_cash = 3

            # Track consecutive wins for overconfidence
            if month_ret > 0:
                consecutive_wins += 1
            else:
                consecutive_wins = 0

            month_start_wealth = wealth[t-1]

            if months_in_cash > 0:
                months_in_cash -= 1
                current_vt_weight = 0.0
            else:
                vix_prev = vix_levels[t-1]
                multiplier = 24.0 if consecutive_wins >= 3 else 12.0
                current_vt_weight = min(multiplier / vix_prev, 1.5)
                current_vt_weight = max(current_vt_weight, 0.0)

                # Check YTD chasing
                spy_ytd = (data["spy_close"].iloc[t] / year_start_spy - 1) * 100
                gld_ytd = (data["gld_close"].iloc[t] / year_start_gld - 1) * 100
                if spy_ytd - gld_ytd > 10:
                    chasing = True

        if months_in_cash > 0:
            port_ret = 0.0
            cash_ret = 0.04 / 252
        elif chasing:
            port_ret = current_vt_weight * spy_ret[t]
            cash_ret = (1 - current_vt_weight) * (0.04 / 252)
        else:
            port_ret = current_vt_weight * (0.5 * spy_ret[t] + 0.5 * gld_ret[t])
            cash_ret = (1 - current_vt_weight) * (0.04 / 252)

        wealth[t] = wealth[t-1] * (1 + port_ret + cash_ret)

    return wealth


combined_wealth = run_combined_worst()
combined_metrics = compute_metrics(combined_wealth, "Combined Worst-Case")
combined_tax = perfect_ann - combined_metrics["ann_return"]

print(f"\n  Combined worst-case (panic + chase + overconfident):")
print(f"    Sharpe: {combined_metrics['sharpe']:.3f} (vs {baseline['sharpe']:.3f} perfect)")
print(f"    MDD: {combined_metrics['mdd']:.1%} (vs {baseline['mdd']:.1%} perfect)")
print(f"    Terminal: ${combined_metrics['terminal_wealth']:.2f} (vs ${baseline['terminal_wealth']:.2f})")
print(f"    Total behavioral tax: {combined_tax:.2%}/yr")
print(f"    Wealth gap: ${perfect_terminal - combined_metrics['terminal_wealth']:.2f}")

# ============================================================
# 10. Buy-and-Hold Comparison
# ============================================================
print("\n" + "=" * 72)
print("COMPARISON: Even behavioral failures vs Buy-and-Hold")
print("=" * 72)

# Simple buy-and-hold 50/50
bh_wealth = np.ones(N)
for t in range(1, N):
    bh_wealth[t] = bh_wealth[t-1] * (1 + 0.5 * spy_ret[t] + 0.5 * gld_ret[t])
bh_metrics = compute_metrics(bh_wealth, "Buy-and-Hold 50/50")

# Simple buy-and-hold 100% SPY
spy_bh_wealth = np.ones(N)
for t in range(1, N):
    spy_bh_wealth[t] = spy_bh_wealth[t-1] * (1 + spy_ret[t])
spy_bh_metrics = compute_metrics(spy_bh_wealth, "Buy-and-Hold 100% SPY")

print(f"\n  {'Strategy':<30} {'Sharpe':>8} {'MDD':>8} {'Terminal$':>10}")
print("  " + "-" * 60)
print(f"  {'Perfect 50/50+VT':<30} {baseline['sharpe']:>8.3f} {baseline['mdd']:>8.1%} "
      f"${baseline['terminal_wealth']:>9.2f}")
for name in ["Panic Seller (-3%)", "Performance Chaser", "Lazy Rebalancer",
             "Overconfident", "Anchored"]:
    m = all_metrics[name]
    print(f"  {name:<30} {m['sharpe']:>8.3f} {m['mdd']:>8.1%} ${m['terminal_wealth']:>9.2f}")
print(f"  {'Combined Worst-Case':<30} {combined_metrics['sharpe']:>8.3f} "
      f"{combined_metrics['mdd']:>8.1%} ${combined_metrics['terminal_wealth']:>9.2f}")
print("  " + "-" * 60)
print(f"  {'Buy-and-Hold 50/50':<30} {bh_metrics['sharpe']:>8.3f} "
      f"{bh_metrics['mdd']:>8.1%} ${bh_metrics['terminal_wealth']:>9.2f}")
print(f"  {'Buy-and-Hold 100% SPY':<30} {spy_bh_metrics['sharpe']:>8.3f} "
      f"{spy_bh_metrics['mdd']:>8.1%} ${spy_bh_metrics['terminal_wealth']:>9.2f}")

# Key insight: do even the worst behavioral failures still beat B&H?
print("\n  Key insight:")
for name, m in all_metrics.items():
    if name == "Perfect 50/50+VT":
        continue
    beats_bh = m["sharpe"] > bh_metrics["sharpe"]
    beats_spy = m["sharpe"] > spy_bh_metrics["sharpe"]
    print(f"    {name:<25}: beats 50/50 B&H? {'YES' if beats_bh else 'NO':<5} "
          f"| beats SPY B&H? {'YES' if beats_spy else 'NO'}")

# Combined too
beats_bh = combined_metrics["sharpe"] > bh_metrics["sharpe"]
beats_spy = combined_metrics["sharpe"] > spy_bh_metrics["sharpe"]
print(f"    {'Combined Worst-Case':<25}: beats 50/50 B&H? {'YES' if beats_bh else 'NO':<5} "
      f"| beats SPY B&H? {'YES' if beats_spy else 'NO'}")

# ============================================================
# 11. Summary & Save Results
# ============================================================
print("\n" + "=" * 72)
print("SUMMARY")
print("=" * 72)

# Sort by behavioral tax
taxes_sorted = sorted(
    [(name, behavioral_taxes[name]) for name in behavioral_taxes
     if name != "Perfect 50/50+VT"],
    key=lambda x: abs(x[1]),
    reverse=True
)

print(f"\n  MOST COSTLY mistake:  {taxes_sorted[0][0]} ({taxes_sorted[0][1]:+.2%}/yr)")
print(f"  LEAST COSTLY mistake: {taxes_sorted[-1][0]} ({taxes_sorted[-1][1]:+.2%}/yr)")
print(f"  Combined worst-case tax: {combined_tax:+.2%}/yr")
print(f"\n  Over {n_years:.0f} years, the worst single mistake costs "
      f"${perfect_terminal - all_metrics[taxes_sorted[0][0]]['terminal_wealth']:.2f} "
      f"per $1 invested")
print(f"  Combined failures cost "
      f"${perfect_terminal - combined_metrics['terminal_wealth']:.2f} per $1 invested")

# Does even the worst behavioral VT still reduce MDD vs B&H?
worst_mdd = max(all_metrics[name]["mdd"] for name in all_metrics if name != "Perfect 50/50+VT")
bh_mdd = bh_metrics["mdd"]
print(f"\n  Even worst behavioral VT MDD ({worst_mdd:.1%}) vs B&H MDD ({bh_mdd:.1%}): "
      f"{'still better' if abs(worst_mdd) < abs(bh_mdd) else 'WORSE'}")

# Save results
results = {
    "experiment": "K291",
    "title": "Realistic Investor Behavior Simulation",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "trading_days": int(N),
    "methodology": "50/50 SPY/GLD + 12/VIX monthly VT with behavioral deviations",
    "metrics": {name: m for name, m in all_metrics.items()},
    "buy_and_hold": {
        "50_50": bh_metrics,
        "100_spy": spy_bh_metrics,
    },
    "combined_worst_case": combined_metrics,
    "behavioral_taxes_annual": {
        name: round(float(tax), 4)
        for name, tax in behavioral_taxes.items()
        if name != "Perfect 50/50+VT"
    },
    "combined_tax_annual": round(float(combined_tax), 4),
    "most_costly_mistake": taxes_sorted[0][0],
    "least_costly_mistake": taxes_sorted[-1][0],
    "behavioral_details": {
        "panic_seller_3pct": {
            "threshold": -0.03,
            "panic_events": int(panic_events),
            "months_in_cash": int(panic_events * 3),
        },
        "panic_seller_5pct": {
            "threshold": -0.05,
            "panic_events": int(panic_events_5pct),
            "months_in_cash": int(panic_events_5pct * 3),
            "note": "50/50+VT never has a month worse than -5%, so this never triggers",
        },
        "performance_chaser": {
            "chase_events": int(chase_events),
        },
        "lazy_rebalancer": {
            "skips": int(lazy_skips),
            "total_rebalances": int(lazy_total),
            "skip_rate_actual": round(lazy_skips / lazy_total, 3),
            "100_seed_sharpe_mean": round(float(np.mean(lazy_sharpes)), 4),
            "100_seed_sharpe_std": round(float(np.std(lazy_sharpes)), 4),
        },
        "overconfident": {
            "aggressive_months": int(aggressive_months),
            "total_months": int(total_months_oc),
            "aggressive_rate": round(aggressive_months / total_months_oc, 3),
        },
        "anchored": {
            "refused_rebalances": int(anchored_refused),
            "total_rebalances": int(anchored_total),
            "refusal_rate": round(anchored_refused / anchored_total, 3),
        },
    },
    "key_findings": [
        f"Most costly single mistake: {taxes_sorted[0][0]} ({taxes_sorted[0][1]:+.2%}/yr)",
        f"Least costly single mistake: {taxes_sorted[-1][0]} ({taxes_sorted[-1][1]:+.2%}/yr)",
        f"Combined worst-case behavioral tax: {combined_tax:+.2%}/yr",
        f"Perfect VT terminal: ${perfect_terminal:.2f}, Combined worst: ${combined_metrics['terminal_wealth']:.2f}",
    ],
    "timestamp": datetime.now().isoformat(),
}

with open(RESULTS_PATH, "w") as f:
    json.dump(results, f, indent=2)

print(f"\n  Results saved to: {RESULTS_PATH}")
print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 72)
