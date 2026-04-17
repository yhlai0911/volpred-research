"""
K293: Life-Cycle Portfolio Path — Complete 40-Year Simulation (Age 25→65→85)
=============================================================================
Building on K292 (DCA investors: 50/50 B&H during accumulation, add VT near retirement).

This experiment simulates the COMPLETE life-cycle path with realistic assumptions:
- Accumulation phase: age 25→65 (40 years) with rising contributions
- Withdrawal phase: age 65→85 (20 years) with 5% annual withdrawal
- Three strategies compared via block bootstrap (5-year blocks)

Data: SPY, GLD, VIX daily from yfinance (2005-2024), block-bootstrapped to 60 years.
"""

import sys
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

N_SIMULATIONS = 500  # number of bootstrap paths
BLOCK_SIZE_YEARS = 5  # block bootstrap block size
TOTAL_YEARS = 60  # 40 accumulation + 20 withdrawal
TRADING_DAYS_PER_YEAR = 252
TRADING_DAYS_PER_MONTH = 21

np.random.seed(42)

# ================================================================
# 1. Download data
# ================================================================
print("=" * 70)
print("K293: Life-Cycle Portfolio Path — 40-Year Simulation")
print("=" * 70)
print(f"\n[1/7] Downloading SPY, GLD, and VIX data (2005-2025)...")

spy_raw = yf.download("SPY", start="2004-12-01", end="2025-01-01", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-12-01", end="2025-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-12-01", end="2025-01-01", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data = data.loc["2005-01-01":"2024-12-31"]

# Compute daily returns
data["spy_ret"] = data["spy_close"].pct_change()
data["gld_ret"] = data["gld_close"].pct_change()
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  SPY ann return: {data['spy_ret'].mean() * 252:.1%}")
print(f"  GLD ann return: {data['gld_ret'].mean() * 252:.1%}")
print(f"  VIX mean: {data['vix_close'].mean():.1f}")

# ================================================================
# 2. Block Bootstrap Infrastructure
# ================================================================
print(f"\n[2/7] Setting up block bootstrap ({N_SIMULATIONS} paths, {BLOCK_SIZE_YEARS}yr blocks)...")

block_size_days = BLOCK_SIZE_YEARS * TRADING_DAYS_PER_YEAR  # ~1260 days
total_days = TOTAL_YEARS * TRADING_DAYS_PER_YEAR  # ~15120 days
n_blocks_needed = int(np.ceil(total_days / block_size_days))

returns_array = data[["spy_ret", "gld_ret"]].values  # (T, 2)
vix_array = data["vix_close"].values  # (T,)
n_obs = len(returns_array)

def generate_bootstrap_path(rng):
    """Generate one 60-year path via block bootstrap of 5-year blocks."""
    path_returns = []
    path_vix = []

    for _ in range(n_blocks_needed):
        # Random start for this block
        max_start = n_obs - block_size_days
        start = rng.integers(0, max_start)
        path_returns.append(returns_array[start:start + block_size_days])
        path_vix.append(vix_array[start:start + block_size_days])

    all_returns = np.concatenate(path_returns, axis=0)[:total_days]
    all_vix = np.concatenate(path_vix)[:total_days]

    return all_returns, all_vix

# ================================================================
# 3. Life-Cycle Contribution Schedule
# ================================================================
print(f"\n[3/7] Building life-cycle contribution schedule...")

# Monthly contributions by age
# Age 25-29: $500/mo, Age 30-39: $1000/mo, Age 40-49: $2000/mo, Age 50-64: $2500/mo
# Age 65-85: withdrawal phase (-5% of portfolio per year, monthly)

def get_monthly_contribution(month_idx):
    """
    month_idx: 0 = start of age 25, 720 = age 85
    Accumulation: months 0-479 (age 25-64, 40 years)
    Withdrawal: months 480-719 (age 65-84, 20 years)
    """
    year_idx = month_idx // 12
    age = 25 + year_idx

    if age < 30:
        return 500.0
    elif age < 40:
        return 1000.0
    elif age < 50:
        return 2000.0
    elif age < 65:
        return 2500.0
    else:
        return None  # withdrawal phase — handled separately

total_months = TOTAL_YEARS * 12  # 720 months

# Total contributions during accumulation
total_contributed = 0.0
for m in range(total_months):
    c = get_monthly_contribution(m)
    if c is not None:
        total_contributed += c
print(f"  Total lifetime contributions: ${total_contributed:,.0f}")
print(f"  Age 25-29: $500/mo  = $30,000 over 5 yrs")
print(f"  Age 30-39: $1,000/mo = $120,000 over 10 yrs")
print(f"  Age 40-49: $2,000/mo = $240,000 over 10 yrs")
print(f"  Age 50-64: $2,500/mo = $450,000 over 15 yrs")
print(f"  Withdrawal: 5% annual (monthly) from age 65")

# ================================================================
# 4. Strategy Definitions
# ================================================================
print(f"\n[4/7] Defining three life-cycle strategies...")

def simulate_strategy_A(returns, vix, rng):
    """
    Strategy A: Life-Cycle 50/50 (K292 recommendation)
    - Age 25-54: Buy-and-hold 50/50 SPY/GLD, NO VT
    - Age 55-59: Add VT overlay (12/VIX), monthly rebalance
    - Age 60-64: Conservative VT (6/VIX), monthly rebalance
    - Age 65-85: Conservative VT (6/VIX), 5% annual withdrawal
    """
    portfolio = 0.0
    monthly_values = []

    for month in range(total_months):
        age = 25 + month // 12

        # Monthly contribution or withdrawal
        contribution = get_monthly_contribution(month)
        if contribution is not None:
            portfolio += contribution
        else:
            # Withdrawal: 5%/year = 0.4167%/month of current portfolio
            withdrawal = portfolio * 0.05 / 12
            portfolio -= withdrawal

        if portfolio <= 0:
            monthly_values.append(0.0)
            continue

        # Simulate one month of returns
        day_start = month * TRADING_DAYS_PER_MONTH
        day_end = min(day_start + TRADING_DAYS_PER_MONTH, len(returns))

        if day_start >= len(returns):
            monthly_values.append(portfolio)
            continue

        month_returns = returns[day_start:day_end]  # (days, 2)
        month_vix = vix[day_start:day_end]

        if age < 55:
            # Pure B&H 50/50 — no VT
            w_spy, w_gld = 0.5, 0.5
            daily_port_ret = month_returns[:, 0] * w_spy + month_returns[:, 1] * w_gld
            month_total_ret = np.prod(1 + daily_port_ret) - 1
        elif age < 60:
            # VT overlay with 12/VIX
            vix_start = month_vix[0] if len(month_vix) > 0 else 20.0
            equity_frac = min(12.0 / vix_start, 1.0)
            w_spy = 0.5 * equity_frac
            w_gld = 0.5 * equity_frac
            cash_frac = 1.0 - equity_frac
            daily_port_ret = month_returns[:, 0] * w_spy + month_returns[:, 1] * w_gld
            month_total_ret = np.prod(1 + daily_port_ret) - 1
        else:
            # Conservative VT with 6/VIX
            vix_start = month_vix[0] if len(month_vix) > 0 else 20.0
            equity_frac = min(6.0 / vix_start, 1.0)
            w_spy = 0.5 * equity_frac
            w_gld = 0.5 * equity_frac
            cash_frac = 1.0 - equity_frac
            daily_port_ret = month_returns[:, 0] * w_spy + month_returns[:, 1] * w_gld
            month_total_ret = np.prod(1 + daily_port_ret) - 1

        portfolio *= (1 + month_total_ret)
        monthly_values.append(portfolio)

    return np.array(monthly_values)


def simulate_strategy_B(returns, vix, rng):
    """
    Strategy B: Always VT (12/VIX from day 1)
    - 50/50 SPY/GLD with 12/VIX overlay throughout
    - Monthly rebalance
    - Same contribution/withdrawal schedule
    """
    portfolio = 0.0
    monthly_values = []

    for month in range(total_months):
        contribution = get_monthly_contribution(month)
        if contribution is not None:
            portfolio += contribution
        else:
            withdrawal = portfolio * 0.05 / 12
            portfolio -= withdrawal

        if portfolio <= 0:
            monthly_values.append(0.0)
            continue

        day_start = month * TRADING_DAYS_PER_MONTH
        day_end = min(day_start + TRADING_DAYS_PER_MONTH, len(returns))

        if day_start >= len(returns):
            monthly_values.append(portfolio)
            continue

        month_returns = returns[day_start:day_end]
        month_vix = vix[day_start:day_end]

        # 12/VIX overlay always
        vix_start = month_vix[0] if len(month_vix) > 0 else 20.0
        equity_frac = min(12.0 / vix_start, 1.0)
        w_spy = 0.5 * equity_frac
        w_gld = 0.5 * equity_frac

        daily_port_ret = month_returns[:, 0] * w_spy + month_returns[:, 1] * w_gld
        month_total_ret = np.prod(1 + daily_port_ret) - 1

        portfolio *= (1 + month_total_ret)
        monthly_values.append(portfolio)

    return np.array(monthly_values)


def simulate_strategy_C(returns, vix, rng):
    """
    Strategy C: Target-Date Fund Proxy (Glide Path)
    - Age 25: 90% equity (45/45 SPY/GLD) + 10% cash
    - Linear glide to age 65: 40% equity (20/20) + 60% cash
    - Age 65-85: stay at 40% equity
    - No VT overlay
    - Monthly rebalance to target allocation
    """
    portfolio = 0.0
    monthly_values = []

    for month in range(total_months):
        age = 25 + month // 12

        contribution = get_monthly_contribution(month)
        if contribution is not None:
            portfolio += contribution
        else:
            withdrawal = portfolio * 0.05 / 12
            portfolio -= withdrawal

        if portfolio <= 0:
            monthly_values.append(0.0)
            continue

        day_start = month * TRADING_DAYS_PER_MONTH
        day_end = min(day_start + TRADING_DAYS_PER_MONTH, len(returns))

        if day_start >= len(returns):
            monthly_values.append(portfolio)
            continue

        month_returns = returns[day_start:day_end]

        # Glide path: 90% equity at 25, linear to 40% at 65, stay 40% after
        if age <= 65:
            equity_pct = 0.90 - (age - 25) * (0.90 - 0.40) / 40.0
        else:
            equity_pct = 0.40

        w_spy = equity_pct / 2
        w_gld = equity_pct / 2

        daily_port_ret = month_returns[:, 0] * w_spy + month_returns[:, 1] * w_gld
        month_total_ret = np.prod(1 + daily_port_ret) - 1

        portfolio *= (1 + month_total_ret)
        monthly_values.append(portfolio)

    return np.array(monthly_values)


print("  Strategy A: Life-Cycle 50/50 (B&H → VT at 55 → Conservative VT at 60)")
print("  Strategy B: Always VT (12/VIX from day 1)")
print("  Strategy C: Target-Date Glide Path (90%→40% equity, no VT)")

# ================================================================
# 5. Run Monte Carlo Simulation
# ================================================================
print(f"\n[5/7] Running {N_SIMULATIONS} bootstrap simulations...")

results_A = np.zeros((N_SIMULATIONS, total_months))
results_B = np.zeros((N_SIMULATIONS, total_months))
results_C = np.zeros((N_SIMULATIONS, total_months))

for i in range(N_SIMULATIONS):
    if (i + 1) % 100 == 0:
        print(f"  ... simulation {i+1}/{N_SIMULATIONS}")

    rng = np.random.default_rng(42 + i)
    path_returns, path_vix = generate_bootstrap_path(rng)

    results_A[i] = simulate_strategy_A(path_returns, path_vix, rng)
    results_B[i] = simulate_strategy_B(path_returns, path_vix, rng)
    results_C[i] = simulate_strategy_C(path_returns, path_vix, rng)

print("  Done.")

# ================================================================
# 6. Analysis
# ================================================================
print(f"\n[6/7] Analyzing results...")
print("=" * 70)

# Key milestones: age 35 (m=120), 45 (m=240), 55 (m=360), 65 (m=480), 75 (m=600), 85 (m=720)
milestones = {
    "Age 35 (10yr)": 119,
    "Age 45 (20yr)": 239,
    "Age 55 (30yr)": 359,
    "Age 65 (retire)": 479,
    "Age 75 (10yr WD)": 599,
    "Age 85 (20yr WD)": 719,
}

# Cumulative contributions at each milestone
cumul_contrib = []
running = 0
for m in range(total_months):
    c = get_monthly_contribution(m)
    if c is not None:
        running += c
    cumul_contrib.append(running)
cumul_contrib = np.array(cumul_contrib)

print("\n--- PORTFOLIO VALUES AT KEY MILESTONES ---")
print(f"{'Milestone':<22} {'Contributed':>12} {'Strategy A':>40} {'Strategy B':>40} {'Strategy C':>40}")
print(f"{'':22} {'':12} {'Median':>12} {'5th%':>12} {'95th%':>12} {'Median':>12} {'5th%':>12} {'95th%':>12} {'Median':>12} {'5th%':>12} {'95th%':>12}")
print("-" * 180)

for label, idx in milestones.items():
    contrib = cumul_contrib[idx]

    med_A = np.median(results_A[:, idx])
    p5_A = np.percentile(results_A[:, idx], 5)
    p95_A = np.percentile(results_A[:, idx], 95)

    med_B = np.median(results_B[:, idx])
    p5_B = np.percentile(results_B[:, idx], 5)
    p95_B = np.percentile(results_B[:, idx], 95)

    med_C = np.median(results_C[:, idx])
    p5_C = np.percentile(results_C[:, idx], 5)
    p95_C = np.percentile(results_C[:, idx], 95)

    print(f"{label:<22} ${contrib:>10,.0f}  ${med_A:>10,.0f} ${p5_A:>10,.0f} ${p95_A:>10,.0f}  "
          f"${med_B:>10,.0f} ${p5_B:>10,.0f} ${p95_B:>10,.0f}  "
          f"${med_C:>10,.0f} ${p5_C:>10,.0f} ${p95_C:>10,.0f}")

# Terminal wealth at retirement (age 65)
print("\n\n--- RETIREMENT ANALYSIS (Age 65) ---")
retire_idx = 479
for name, results in [("A: Life-Cycle 50/50", results_A),
                       ("B: Always VT", results_B),
                       ("C: Target-Date", results_C)]:
    vals = results[:, retire_idx]
    print(f"\n  Strategy {name}:")
    print(f"    Median wealth at 65: ${np.median(vals):>12,.0f}")
    print(f"    Mean wealth at 65:   ${np.mean(vals):>12,.0f}")
    print(f"    5th percentile:      ${np.percentile(vals, 5):>12,.0f}")
    print(f"    25th percentile:     ${np.percentile(vals, 25):>12,.0f}")
    print(f"    75th percentile:     ${np.percentile(vals, 75):>12,.0f}")
    print(f"    95th percentile:     ${np.percentile(vals, 95):>12,.0f}")
    print(f"    Total contributed:   ${total_contributed:>12,.0f}")
    print(f"    Median multiple:     {np.median(vals)/total_contributed:>12.1f}x")

# Withdrawal phase analysis
print("\n\n--- WITHDRAWAL PHASE ANALYSIS (Age 65→85) ---")
print("  5% annual withdrawal rate, monthly")

for name, results in [("A: Life-Cycle 50/50", results_A),
                       ("B: Always VT", results_B),
                       ("C: Target-Date", results_C)]:
    # Check ruin probability
    final_vals = results[:, -1]  # age 85
    ruin_count = np.sum(final_vals <= 0)
    ruin_prob = ruin_count / N_SIMULATIONS

    # Check when portfolio hits zero (if ever)
    ruin_months = []
    for i in range(N_SIMULATIONS):
        path = results[i, retire_idx:]  # withdrawal phase only
        zero_idx = np.where(path <= 0)[0]
        if len(zero_idx) > 0:
            ruin_months.append(zero_idx[0])

    print(f"\n  Strategy {name}:")
    print(f"    Ruin probability (20yr): {ruin_prob:.1%} ({ruin_count}/{N_SIMULATIONS})")
    print(f"    Median wealth at 85:     ${np.median(final_vals):>12,.0f}")
    print(f"    5th percentile at 85:    ${np.percentile(final_vals, 5):>12,.0f}")
    print(f"    95th percentile at 85:   ${np.percentile(final_vals, 95):>12,.0f}")

    if len(ruin_months) > 0:
        median_ruin_month = np.median(ruin_months)
        print(f"    Median ruin time:        {median_ruin_month/12:.1f} years into withdrawal")
    else:
        print(f"    No ruin observed in any simulation")

    # Wealth preservation ratio
    retire_vals = results[:, retire_idx]
    preservation = final_vals / np.where(retire_vals > 0, retire_vals, 1)
    print(f"    Median preservation:     {np.median(preservation):.1%} of retirement wealth remaining")

# ================================================================
# 6b. Maximum Drawdown during accumulation
# ================================================================
print("\n\n--- MAXIMUM DRAWDOWN DURING ACCUMULATION (Age 25-65) ---")

for name, results in [("A: Life-Cycle 50/50", results_A),
                       ("B: Always VT", results_B),
                       ("C: Target-Date", results_C)]:
    mdds = []
    for i in range(N_SIMULATIONS):
        path = results[i, :retire_idx+1]
        # Only meaningful after some accumulation (year 3+)
        path_from_3yr = path[36:]  # skip first 3 years
        if len(path_from_3yr) > 0 and np.max(path_from_3yr) > 0:
            running_max = np.maximum.accumulate(path_from_3yr)
            running_max = np.where(running_max > 0, running_max, 1)
            drawdowns = (path_from_3yr - running_max) / running_max
            mdd = np.min(drawdowns)
            mdds.append(mdd)

    mdds = np.array(mdds)
    print(f"\n  Strategy {name}:")
    print(f"    Median MDD: {np.median(mdds):.1%}")
    print(f"    5th pct MDD: {np.percentile(mdds, 5):.1%}  (worst 5%)")
    print(f"    95th pct MDD: {np.percentile(mdds, 95):.1%}  (best 5%)")

# ================================================================
# 6c. Statistical Tests
# ================================================================
print("\n\n--- STATISTICAL COMPARISONS ---")

# Paired test at retirement (age 65)
retire_A = results_A[:, retire_idx]
retire_B = results_B[:, retire_idx]
retire_C = results_C[:, retire_idx]

# A vs B
diff_AB = retire_A - retire_B
t_AB, p_AB = stats.ttest_1samp(diff_AB, 0)
print(f"\n  A vs B (at retirement):")
print(f"    Mean diff: ${np.mean(diff_AB):>12,.0f}")
print(f"    t-stat: {t_AB:.3f}, p-value: {p_AB:.4f}")
print(f"    A wins: {np.mean(diff_AB > 0):.1%} of simulations")

# A vs C
diff_AC = retire_A - retire_C
t_AC, p_AC = stats.ttest_1samp(diff_AC, 0)
print(f"\n  A vs C (at retirement):")
print(f"    Mean diff: ${np.mean(diff_AC):>12,.0f}")
print(f"    t-stat: {t_AC:.3f}, p-value: {p_AC:.4f}")
print(f"    A wins: {np.mean(diff_AC > 0):.1%} of simulations")

# B vs C
diff_BC = retire_B - retire_C
t_BC, p_BC = stats.ttest_1samp(diff_BC, 0)
print(f"\n  B vs C (at retirement):")
print(f"    Mean diff: ${np.mean(diff_BC):>12,.0f}")
print(f"    t-stat: {t_BC:.3f}, p-value: {p_BC:.4f}")
print(f"    B wins: {np.mean(diff_BC > 0):.1%} of simulations")

# Same tests at age 85 (end of withdrawal)
final_A = results_A[:, -1]
final_B = results_B[:, -1]
final_C = results_C[:, -1]

diff_AB_85 = final_A - final_B
t_AB_85, p_AB_85 = stats.ttest_1samp(diff_AB_85, 0)
print(f"\n  A vs B (at age 85):")
print(f"    Mean diff: ${np.mean(diff_AB_85):>12,.0f}")
print(f"    t-stat: {t_AB_85:.3f}, p-value: {p_AB_85:.4f}")
print(f"    A wins: {np.mean(diff_AB_85 > 0):.1%} of simulations")

diff_AC_85 = final_A - final_C
t_AC_85, p_AC_85 = stats.ttest_1samp(diff_AC_85, 0)
print(f"\n  A vs C (at age 85):")
print(f"    Mean diff: ${np.mean(diff_AC_85):>12,.0f}")
print(f"    t-stat: {t_AC_85:.3f}, p-value: {p_AC_85:.4f}")
print(f"    A wins: {np.mean(diff_AC_85 > 0):.1%} of simulations")

# ================================================================
# 6d. VT Insurance Cost Analysis
# ================================================================
print("\n\n--- VT INSURANCE COST (Strategy B vs A during accumulation) ---")
# How much does VT cost during accumulation years?
for age_label, start_m, end_m in [("Age 25-34", 0, 119),
                                   ("Age 35-44", 120, 239),
                                   ("Age 45-54", 240, 359),
                                   ("Age 55-64", 360, 479)]:
    vals_A = results_A[:, end_m]
    vals_B = results_B[:, end_m]
    pct_diff = (vals_B - vals_A) / np.where(vals_A > 0, vals_A, 1) * 100
    print(f"  {age_label}: VT median cost = {np.median(pct_diff):+.1f}% of no-VT portfolio")

# ================================================================
# 6e. Sequence-of-Returns Risk
# ================================================================
print("\n\n--- SEQUENCE-OF-RETURNS RISK (Worst 10% paths) ---")
# Compare worst outcomes — where VT matters most
for name, results in [("A: Life-Cycle", results_A),
                       ("B: Always VT", results_B),
                       ("C: Target-Date", results_C)]:
    final = results[:, -1]
    worst_10 = np.percentile(final, 10)
    worst_5 = np.percentile(final, 5)
    worst_1 = np.percentile(final, 1)
    print(f"  {name}: 10th%=${worst_10:>10,.0f}  5th%=${worst_5:>10,.0f}  1st%=${worst_1:>10,.0f}")

# ================================================================
# 7. Summary & Recommendation
# ================================================================
print("\n\n" + "=" * 70)
print("SUMMARY: THE DEFINITIVE LIFE-CYCLE ANSWER")
print("=" * 70)

# Determine winner at each phase
winner_retire = "A" if np.median(retire_A) > max(np.median(retire_B), np.median(retire_C)) else \
                "B" if np.median(retire_B) > np.median(retire_C) else "C"
winner_final = "A" if np.median(final_A) > max(np.median(final_B), np.median(final_C)) else \
               "B" if np.median(final_B) > np.median(final_C) else "C"

winner_map = {"A": "Life-Cycle 50/50", "B": "Always VT", "C": "Target-Date"}

print(f"\n  Highest median wealth at retirement (65): Strategy {winner_retire} ({winner_map[winner_retire]})")
print(f"  Highest median wealth at 85:              Strategy {winner_final} ({winner_map[winner_final]})")

# Ruin comparison
ruin_A = np.sum(final_A <= 0) / N_SIMULATIONS
ruin_B = np.sum(final_B <= 0) / N_SIMULATIONS
ruin_C = np.sum(final_C <= 0) / N_SIMULATIONS
print(f"\n  Ruin probability (20yr withdrawal):")
print(f"    A: {ruin_A:.1%}  |  B: {ruin_B:.1%}  |  C: {ruin_C:.1%}")

# Risk-adjusted (worst-case protection)
worst5_A = np.percentile(final_A, 5)
worst5_B = np.percentile(final_B, 5)
worst5_C = np.percentile(final_C, 5)
best_worst = "A" if worst5_A > max(worst5_B, worst5_C) else \
             "B" if worst5_B > worst5_C else "C"
print(f"\n  Best worst-case (5th percentile at 85): Strategy {best_worst} ({winner_map[best_worst]})")
print(f"    A: ${worst5_A:>10,.0f}  |  B: ${worst5_B:>10,.0f}  |  C: ${worst5_C:>10,.0f}")

# Practical recommendation
print(f"\n  === PRACTICAL RECOMMENDATION FOR A 25-YEAR-OLD ===")
print(f"  1. Start with 50/50 SPY/GLD, contribute consistently, NO VT overlay")
print(f"     (VT costs ~1-4%/yr in insurance premium during bull markets)")
print(f"  2. At age 55 (10 years before retirement), add 12/VIX monthly VT")
print(f"     (protects accumulated wealth from sequence-of-returns risk)")
print(f"  3. At age 60, switch to conservative 6/VIX VT")
print(f"  4. At retirement, maintain 6/VIX VT with 5% withdrawal rate")
print(f"  5. Total lifetime contributions: ${total_contributed:,.0f}")
print(f"     Expected median retirement wealth: ${np.median(retire_A):,.0f}")
print(f"     Expected multiple: {np.median(retire_A)/total_contributed:.1f}x")

# ================================================================
# Save results
# ================================================================
results_dict = {
    "experiment": "K293",
    "title": "Life-Cycle Portfolio Path — 40-Year Simulation",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "methodology": {
        "type": "block_bootstrap_monte_carlo",
        "n_simulations": N_SIMULATIONS,
        "block_size_years": BLOCK_SIZE_YEARS,
        "total_years": TOTAL_YEARS,
        "accumulation_years": 40,
        "withdrawal_years": 20,
        "withdrawal_rate": "5% annual"
    },
    "contributions": {
        "age_25_29": "$500/month",
        "age_30_39": "$1,000/month",
        "age_40_49": "$2,000/month",
        "age_50_64": "$2,500/month",
        "total_contributed": total_contributed
    },
    "strategies": {
        "A_lifecycle": "50/50 B&H age 25-54, 12/VIX VT age 55-59, 6/VIX VT age 60+",
        "B_always_vt": "50/50 with 12/VIX VT from age 25",
        "C_target_date": "Glide path 90%→40% equity, no VT"
    },
    "results_at_retirement": {
        "strategy_A": {
            "median": float(np.median(retire_A)),
            "mean": float(np.mean(retire_A)),
            "p5": float(np.percentile(retire_A, 5)),
            "p25": float(np.percentile(retire_A, 25)),
            "p75": float(np.percentile(retire_A, 75)),
            "p95": float(np.percentile(retire_A, 95)),
            "multiple": float(np.median(retire_A) / total_contributed)
        },
        "strategy_B": {
            "median": float(np.median(retire_B)),
            "mean": float(np.mean(retire_B)),
            "p5": float(np.percentile(retire_B, 5)),
            "p25": float(np.percentile(retire_B, 25)),
            "p75": float(np.percentile(retire_B, 75)),
            "p95": float(np.percentile(retire_B, 95)),
            "multiple": float(np.median(retire_B) / total_contributed)
        },
        "strategy_C": {
            "median": float(np.median(retire_C)),
            "mean": float(np.mean(retire_C)),
            "p5": float(np.percentile(retire_C, 5)),
            "p25": float(np.percentile(retire_C, 25)),
            "p75": float(np.percentile(retire_C, 75)),
            "p95": float(np.percentile(retire_C, 95)),
            "multiple": float(np.median(retire_C) / total_contributed)
        }
    },
    "results_at_85": {
        "strategy_A": {
            "median": float(np.median(final_A)),
            "p5": float(np.percentile(final_A, 5)),
            "p95": float(np.percentile(final_A, 95)),
            "ruin_probability": float(ruin_A)
        },
        "strategy_B": {
            "median": float(np.median(final_B)),
            "p5": float(np.percentile(final_B, 5)),
            "p95": float(np.percentile(final_B, 95)),
            "ruin_probability": float(ruin_B)
        },
        "strategy_C": {
            "median": float(np.median(final_C)),
            "p5": float(np.percentile(final_C, 5)),
            "p95": float(np.percentile(final_C, 95)),
            "ruin_probability": float(ruin_C)
        }
    },
    "statistical_tests": {
        "A_vs_B_retirement": {"t_stat": float(t_AB), "p_value": float(p_AB), "A_win_rate": float(np.mean(diff_AB > 0))},
        "A_vs_C_retirement": {"t_stat": float(t_AC), "p_value": float(p_AC), "A_win_rate": float(np.mean(diff_AC > 0))},
        "B_vs_C_retirement": {"t_stat": float(t_BC), "p_value": float(p_BC), "B_win_rate": float(np.mean(diff_BC > 0))},
        "A_vs_B_age85": {"t_stat": float(t_AB_85), "p_value": float(p_AB_85), "A_win_rate": float(np.mean(diff_AB_85 > 0))},
        "A_vs_C_age85": {"t_stat": float(t_AC_85), "p_value": float(p_AC_85), "A_win_rate": float(np.mean(diff_AC_85 > 0))}
    },
    "winner_retirement": winner_retire,
    "winner_final": winner_final,
    "best_worst_case": best_worst
}

output_path = "experiments/k293_lifecycle_results.json"
with open(output_path, "w") as f:
    json.dump(results_dict, f, indent=2)
print(f"\n  Results saved to {output_path}")
print(f"\n{'=' * 70}")
print("K293 COMPLETE")
print("=" * 70)
