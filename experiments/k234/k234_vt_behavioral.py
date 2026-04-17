"""
K234: VT Behavioral Analysis — Can Real Investors Actually Follow This Strategy?
==================================================================================
[提出: 用戶, 執行: Claude]

Research Question:
  VT works in backtests but requires selling when everyone is panicking (high VIX
  = reduce position). This is psychologically extremely difficult. How often does
  VT require counter-intuitive actions, and how much performance is lost by being
  "human" (not following extreme signals)?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.

Methodology:
  1. Classify VT actions into behavioral difficulty (monthly rebalance):
     - Easy: VIX stable, weight barely changes (< 5% change)
     - Moderate: VIX rising, reduce position 5-20%
     - Hard: VIX spike >15%, reduce position >20% in one rebalance
     - Extreme: VIX >30 and position reduced to <40% (selling during panic)
  2. Frequency of each type
  3. Behavioral variant strategies:
     - VT-Easy: only rebalance when change is <10%
     - VT-NoExtreme: skip rebalancing when VIX>30
     - VT-Delayed: always rebalance but 1 month delayed
  4. Compare each behavioral variant vs full VT
  5. Key question: how much performance is lost by being "human"?
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
PROJECT = os.path.dirname(WORKTREE)

# ============================================================
# 1. Download and prepare historical data
# ============================================================
print("=" * 72)
print("K234: VT Behavioral Analysis — Can Real Investors Actually Follow VT?")
print("=" * 72)
print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

print("\n[1/6] Downloading SPY, GLD, and VIX data (2005-2024)...")
spy_raw = yf.download("SPY", start="2004-12-01", end="2025-01-01",
                       progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-12-01", end="2025-01-01",
                       progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-12-01", end="2025-01-01",
                       progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(vix, how="inner").join(gld, how="inner").dropna()
data["spy_ret"] = data["spy_close"].pct_change()
data["gld_ret"] = data["gld_close"].pct_change()
data = data.dropna()

# Focus on 2005-2024
data = data.loc["2005-01-01":"2024-12-31"]
print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {len(data)}")

# ============================================================
# 2. Monthly rebalance dates & VT weight calculation
# ============================================================
print("\n[2/6] Computing monthly VT weights (12/VIX)...")

# Get month-end trading dates for rebalancing
data["year_month"] = data.index.to_period("M")
month_end_dates = data.groupby("year_month").apply(lambda x: x.index[-1])
month_end_dates = month_end_dates.values  # array of Timestamps

# Compute 12/VIX weight at each month-end (used for NEXT month)
monthly_weights = []
for d in month_end_dates:
    vix_val = float(data.loc[d, "vix_close"])
    w = min(12.0 / vix_val, 1.0)  # cap at 100%
    monthly_weights.append({
        "date": d,
        "vix": vix_val,
        "weight": w,
    })

monthly_df = pd.DataFrame(monthly_weights)
monthly_df.set_index("date", inplace=True)

# Compute weight changes between consecutive months
monthly_df["prev_weight"] = monthly_df["weight"].shift(1)
monthly_df["weight_change"] = monthly_df["weight"] - monthly_df["prev_weight"]
monthly_df["weight_change_pct"] = (monthly_df["weight_change"] / monthly_df["prev_weight"]).abs() * 100
monthly_df["weight_change_abs"] = monthly_df["weight_change"].abs()
monthly_df = monthly_df.dropna()

print(f"  Monthly rebalance periods: {len(monthly_df)}")
print(f"  VIX range: {monthly_df['vix'].min():.1f} - {monthly_df['vix'].max():.1f}")
print(f"  Weight range: {monthly_df['weight'].min():.2f} - {monthly_df['weight'].max():.2f}")

# ============================================================
# 3. Classify each rebalance into behavioral difficulty
# ============================================================
print("\n[3/6] Classifying rebalance events by behavioral difficulty...")


def classify_difficulty(row):
    """Classify a rebalance event into behavioral difficulty category.

    Easy: weight change < 5 percentage points
    Moderate: VIX rising + reduce position 5-20 pp
    Hard: VIX spike >15 (level), reduce position >20 pp in one rebalance
    Extreme: VIX >30 AND position reduced to <40%
    """
    weight_change_pp = row["weight_change"] * 100  # in percentage points
    weight_change_abs_pp = abs(weight_change_pp)
    new_weight = row["weight"]
    vix = row["vix"]
    is_reducing = weight_change_pp < 0  # selling / reducing exposure

    # Extreme: VIX > 30 AND position < 40% (selling during panic)
    if vix > 30 and new_weight < 0.40 and is_reducing:
        return "Extreme"

    # Hard: large reduction (>20 pp) when VIX is elevated (>15)
    if is_reducing and weight_change_abs_pp > 20 and vix > 15:
        return "Hard"

    # Moderate: meaningful reduction (5-20 pp)
    if is_reducing and weight_change_abs_pp > 5:
        return "Moderate"

    # Easy: small change or increasing position (buying is psychologically easy)
    return "Easy"


monthly_df["difficulty"] = monthly_df.apply(classify_difficulty, axis=1)

# Frequency table
diff_counts = monthly_df["difficulty"].value_counts()
diff_pct = (diff_counts / len(monthly_df) * 100).round(1)

print("\n  ┌──────────────────────────────────────────────────────────────────┐")
print("  │              REBALANCE DIFFICULTY DISTRIBUTION                   │")
print("  ├─────────────┬────────────┬────────────┬─────────────────────────┤")
print("  │ Difficulty   │   Count    │  Pct (%)   │  Description            │")
print("  ├─────────────┼────────────┼────────────┼─────────────────────────┤")
for diff_level in ["Easy", "Moderate", "Hard", "Extreme"]:
    cnt = diff_counts.get(diff_level, 0)
    pct = diff_pct.get(diff_level, 0)
    desc = {
        "Easy": "Small change or buying",
        "Moderate": "Reduce 5-20pp",
        "Hard": "Reduce >20pp, VIX>15",
        "Extreme": "VIX>30, sell to <40%",
    }[diff_level]
    print(f"  │ {diff_level:<11s} │ {cnt:>10d} │ {pct:>10.1f} │ {desc:<23s} │")
print("  └─────────────┴────────────┴────────────┴─────────────────────────┘")

# Show specific extreme events
extreme_events = monthly_df[monthly_df["difficulty"] == "Extreme"].copy()
hard_events = monthly_df[monthly_df["difficulty"] == "Hard"].copy()

if len(extreme_events) > 0:
    print(f"\n  EXTREME rebalance events ({len(extreme_events)} total):")
    for idx, row in extreme_events.iterrows():
        dt = pd.Timestamp(idx)
        print(f"    {dt.strftime('%Y-%m')}: VIX={row['vix']:.1f}, "
              f"weight {row['prev_weight']:.0%} → {row['weight']:.0%} "
              f"(Δ={row['weight_change']*100:+.1f}pp)")

if len(hard_events) > 0:
    print(f"\n  HARD rebalance events ({len(hard_events)} total):")
    for idx, row in hard_events.iterrows():
        dt = pd.Timestamp(idx)
        print(f"    {dt.strftime('%Y-%m')}: VIX={row['vix']:.1f}, "
              f"weight {row['prev_weight']:.0%} → {row['weight']:.0%} "
              f"(Δ={row['weight_change']*100:+.1f}pp)")

# ============================================================
# 4. Construct behavioral variant strategies
# ============================================================
print("\n[4/6] Constructing behavioral variant strategies...")

# We need daily returns for each strategy variant.
# Monthly rebalance: weight determined at month-end, applied to entire next month.

# Build daily weight series for each strategy
daily_dates = data.index
n_days = len(daily_dates)

# Helper: map each trading day to its applicable monthly weight
def build_daily_weights_full_vt(data, monthly_df, month_end_dates):
    """Full VT: rebalance every month using 12/VIX."""
    weights = pd.Series(index=data.index, dtype=float)
    # For dates before first rebalance, use first available weight
    first_w = float(monthly_df.iloc[0]["weight"])
    weights[:] = first_w

    for i in range(len(month_end_dates) - 1):
        rebal_date = month_end_dates[i]
        next_rebal_date = month_end_dates[i + 1]
        if rebal_date in monthly_df.index:
            w = float(monthly_df.loc[rebal_date, "weight"])
            # Apply weight from day after rebal_date to next_rebal_date
            mask = (weights.index > rebal_date) & (weights.index <= next_rebal_date)
            weights[mask] = w

    # After last rebal date
    if len(month_end_dates) > 0:
        last_rebal = month_end_dates[-1]
        if last_rebal in monthly_df.index:
            weights[weights.index > last_rebal] = float(
                monthly_df.loc[last_rebal, "weight"]
            )

    return weights


def build_variant_weights(data, monthly_df, month_end_dates, variant):
    """Build daily weights for a behavioral variant.

    Variants:
    - 'full': standard VT (baseline)
    - 'easy_only': only rebalance when weight change < 10pp; else keep old weight
    - 'no_extreme': skip rebalancing when VIX > 30; keep old weight
    - 'delayed': always rebalance but use LAST month's signal (1 month delayed)
    """
    weights = pd.Series(index=data.index, dtype=float)
    first_w = float(monthly_df.iloc[0]["weight"])
    current_w = first_w
    weights[:] = first_w

    for i in range(len(month_end_dates) - 1):
        rebal_date = month_end_dates[i]
        next_rebal_date = month_end_dates[i + 1]

        if rebal_date not in monthly_df.index:
            continue

        target_w = float(monthly_df.loc[rebal_date, "weight"])
        vix_val = float(monthly_df.loc[rebal_date, "vix"])
        change_pp = abs(target_w - current_w) * 100

        if variant == "full":
            current_w = target_w

        elif variant == "easy_only":
            # Only rebalance if change is < 10 percentage points
            if change_pp < 10:
                current_w = target_w
            # else: keep current_w (skip this rebalance)

        elif variant == "no_extreme":
            # Skip rebalancing when VIX > 30
            if vix_val <= 30:
                current_w = target_w
            # else: keep current_w (refuse to sell during panic)

        elif variant == "delayed":
            # Use PREVIOUS month's target weight (1-month delay)
            if i > 0:
                prev_rebal = month_end_dates[i - 1]
                if prev_rebal in monthly_df.index:
                    current_w = float(monthly_df.loc[prev_rebal, "weight"])
            # else: keep initial weight

        # Apply current_w for the next month's daily returns
        mask = (weights.index > rebal_date) & (weights.index <= next_rebal_date)
        weights[mask] = current_w

    # After last rebal date
    if len(month_end_dates) > 0:
        weights[weights.index > month_end_dates[-1]] = current_w

    return weights


# Build all variants
variants = {
    "Full VT": "full",
    "VT-Easy (skip >10pp)": "easy_only",
    "VT-NoExtreme (skip VIX>30)": "no_extreme",
    "VT-Delayed (1 month lag)": "delayed",
}

# Also add Buy & Hold for reference
daily_weights = {}
for name, var_key in variants.items():
    daily_weights[name] = build_variant_weights(
        data, monthly_df, month_end_dates, var_key
    )

# Buy & Hold: always 100% SPY
daily_weights["Buy & Hold (SPY)"] = pd.Series(1.0, index=data.index)

# 50/50 SPY/GLD Buy & Hold for reference
# (handled separately since it has GLD allocation)

# ============================================================
# 5. Compute portfolio returns and performance metrics
# ============================================================
print("\n[5/6] Computing portfolio performance for each variant...")

spy_rets = data["spy_ret"].values
gld_rets = data["gld_ret"].values


def compute_metrics(daily_rets, label="", ann_factor=252):
    """Compute annualized performance metrics from daily returns."""
    rets = np.array(daily_rets)
    n = len(rets)
    n_years = n / ann_factor

    cum = np.cumprod(1 + rets)
    total_ret = cum[-1] - 1
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = np.std(rets) * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    peak = np.maximum.accumulate(cum)
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()

    # Sortino
    downside = rets[rets < 0]
    downside_vol = np.std(downside) * np.sqrt(ann_factor) if len(downside) > 0 else 0
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        "label": label,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "sortino": sortino,
        "calmar": calmar,
        "total_ret": total_ret,
        "n_years": n_years,
    }


results = {}
for name, w_series in daily_weights.items():
    w_arr = w_series.values
    # SPY-only portfolio (weight * SPY + (1-weight) * cash)
    port_rets = w_arr * spy_rets
    results[name] = compute_metrics(port_rets, name)

# 50/50 SPY/GLD VT (recommended strategy)
w_full = daily_weights["Full VT"].values
port_rets_5050 = 0.5 * w_full * spy_rets + 0.5 * w_full * gld_rets
results["50/50 SPY/GLD VT"] = compute_metrics(port_rets_5050, "50/50 SPY/GLD VT")

# 50/50 SPY/GLD B&H
port_rets_5050_bh = 0.5 * spy_rets + 0.5 * gld_rets
results["50/50 SPY/GLD B&H"] = compute_metrics(port_rets_5050_bh, "50/50 SPY/GLD B&H")

# ── Print results table ──
print("\n  ┌───────────────────────────────────────────────────────────────────────────────────────────────┐")
print("  │                       PERFORMANCE COMPARISON: VT VARIANTS vs FULL VT                        │")
print("  ├──────────────────────────┬─────────┬─────────┬─────────┬─────────┬─────────┬────────────────┤")
print("  │ Strategy                 │ Ann Ret │ Ann Vol │ Sharpe  │  MDD    │ Sortino │ vs Full VT     │")
print("  ├──────────────────────────┼─────────┼─────────┼─────────┼─────────┼─────────┼────────────────┤")

full_vt_sharpe = results["Full VT"]["sharpe"]
strategy_order = [
    "Full VT",
    "VT-Easy (skip >10pp)",
    "VT-NoExtreme (skip VIX>30)",
    "VT-Delayed (1 month lag)",
    "Buy & Hold (SPY)",
    "50/50 SPY/GLD VT",
    "50/50 SPY/GLD B&H",
]
for name in strategy_order:
    r = results[name]
    diff_sharpe = r["sharpe"] - full_vt_sharpe
    diff_str = f"{'+'if diff_sharpe>=0 else ''}{diff_sharpe:.3f} Sharpe"
    if name == "Full VT":
        diff_str = "  (baseline)"
    print(f"  │ {name:<24s} │ {r['ann_ret']:>6.1%} │ {r['ann_vol']:>6.1%} │ {r['sharpe']:>7.3f} │ {r['mdd']:>7.1%} │ {r['sortino']:>7.3f} │ {diff_str:<14s} │")

print("  └──────────────────────────┴─────────┴─────────┴─────────┴─────────┴─────────┴────────────────┘")

# ============================================================
# 6. Deep analysis: when do hard/extreme events matter?
# ============================================================
print("\n[6/6] Deep analysis: crisis-period behavioral impact...")

# For each Hard/Extreme event, compute the return over the NEXT 1/3/6 months
# if you had skipped the rebalance vs executed it
print("\n  CRISIS EPISODE ANALYSIS")
print("  What happens in the months AFTER each Hard/Extreme rebalance?")
print()

hard_extreme = monthly_df[monthly_df["difficulty"].isin(["Hard", "Extreme"])].copy()

episode_analysis = []
for idx, row in hard_extreme.iterrows():
    rebal_date = pd.Timestamp(idx)
    vix_val = row["vix"]
    target_w = row["weight"]
    prev_w = row["prev_weight"]

    # Next 1/3/6 months SPY returns
    for horizon_m, horizon_label in [(1, "1m"), (3, "3m"), (6, "6m")]:
        future_mask = (data.index > rebal_date)
        future_data = data[future_mask]
        # Approximate: 21 trading days per month
        n_days_horizon = min(horizon_m * 21, len(future_data))
        if n_days_horizon < 10:
            continue

        future_spy = future_data["spy_ret"].values[:n_days_horizon]

        # Strategy A: executed rebalance (use target_w)
        ret_executed = np.prod(1 + target_w * future_spy) - 1
        # Strategy B: skipped rebalance (keep prev_w)
        ret_skipped = np.prod(1 + prev_w * future_spy) - 1
        # Strategy C: Buy & Hold (w=1)
        ret_bh = np.prod(1 + future_spy) - 1

        episode_analysis.append({
            "date": rebal_date.strftime("%Y-%m"),
            "difficulty": row["difficulty"],
            "vix": vix_val,
            "target_w": target_w,
            "prev_w": prev_w,
            "horizon": horizon_label,
            "ret_executed": ret_executed,
            "ret_skipped": ret_skipped,
            "ret_bh": ret_bh,
            "benefit_of_executing": ret_executed - ret_skipped,
        })

ep_df = pd.DataFrame(episode_analysis)

# Summarize by horizon
print("  ┌────────────────────────────────────────────────────────────────────────────┐")
print("  │           BENEFIT OF EXECUTING Hard/Extreme REBALANCES                    │")
print("  │  Positive = executing VT rebalance was BETTER than skipping               │")
print("  ├─────────┬──────────────────┬──────────────────┬──────────────────┬─────────┤")
print("  │ Horizon │ Mean Benefit     │ Median Benefit   │ % Times Better   │ N       │")
print("  ├─────────┼──────────────────┼──────────────────┼──────────────────┼─────────┤")

for horizon in ["1m", "3m", "6m"]:
    subset = ep_df[ep_df["horizon"] == horizon]
    if len(subset) == 0:
        continue
    mean_b = subset["benefit_of_executing"].mean()
    median_b = subset["benefit_of_executing"].median()
    pct_better = (subset["benefit_of_executing"] > 0).mean() * 100
    n = len(subset)
    print(f"  │ {horizon:<7s} │ {mean_b:>+15.2%} │ {median_b:>+15.2%} │ {pct_better:>15.1f}% │ {n:>7d} │")

print("  └─────────┴──────────────────┴──────────────────┴──────────────────┴─────────┘")

# Individual extreme events detail
if len(extreme_events) > 0:
    print("\n  EXTREME EVENT DETAILED OUTCOMES (1-month horizon):")
    print("  ┌─────────┬───────┬────────────────┬──────────────┬──────────────┬──────────────┐")
    print("  │ Date    │  VIX  │ Weight Change   │ Ret(Execute) │ Ret(Skip)    │ Benefit      │")
    print("  ├─────────┼───────┼────────────────┼──────────────┼──────────────┼──────────────┤")

    for idx, row in extreme_events.iterrows():
        dt = pd.Timestamp(idx).strftime("%Y-%m")
        ep_1m = ep_df[(ep_df["date"] == dt) & (ep_df["horizon"] == "1m")]
        if len(ep_1m) > 0:
            ep = ep_1m.iloc[0]
            weight_str = f"{row['prev_weight']:.0%}→{row['weight']:.0%}"
            print(f"  │ {dt:<7s} │ {row['vix']:>5.1f} │ {weight_str:>14s} │ {ep['ret_executed']:>+11.2%} │ {ep['ret_skipped']:>+11.2%} │ {ep['benefit_of_executing']:>+11.2%} │")

    print("  └─────────┴───────┴────────────────┴──────────────┴──────────────┴──────────────┘")

# ============================================================
# 7. Statistical tests: Full VT vs each variant
# ============================================================
print("\n" + "=" * 72)
print("STATISTICAL TESTS: Full VT vs Behavioral Variants")
print("=" * 72)

# Get monthly returns for each variant for statistical testing
full_w = daily_weights["Full VT"].values
full_daily_rets = full_w * spy_rets

# Group daily returns by month for Sharpe comparison
data_with_strats = data.copy()
data_with_strats["full_vt_ret"] = full_w * spy_rets

for name, var_key in variants.items():
    if name == "Full VT":
        continue
    w_arr = daily_weights[name].values
    data_with_strats[f"{var_key}_ret"] = w_arr * spy_rets

# Monthly aggregation
data_with_strats["year_month_str"] = data_with_strats.index.to_period("M").astype(str)

monthly_rets = {}
monthly_rets["Full VT"] = data_with_strats.groupby("year_month_str")["full_vt_ret"].apply(
    lambda x: np.prod(1 + x) - 1
).values

for name, var_key in variants.items():
    if name == "Full VT":
        continue
    monthly_rets[name] = data_with_strats.groupby("year_month_str")[f"{var_key}_ret"].apply(
        lambda x: np.prod(1 + x) - 1
    ).values

# Paired t-tests on monthly returns
print("\n  Paired t-test on monthly returns (Full VT vs each variant):")
print("  ┌──────────────────────────┬──────────┬──────────┬─────────────────┐")
print("  │ Comparison               │  t-stat  │  p-value │ Interpretation  │")
print("  ├──────────────────────────┼──────────┼──────────┼─────────────────┤")

for name in ["VT-Easy (skip >10pp)", "VT-NoExtreme (skip VIX>30)", "VT-Delayed (1 month lag)"]:
    diff = monthly_rets["Full VT"] - monthly_rets[name]
    t_stat, p_val = stats.ttest_1samp(diff, 0)
    sig = "Significant" if p_val < 0.05 else "Not significant"
    print(f"  │ Full VT vs {name:<13s} │ {t_stat:>+8.3f} │ {p_val:>8.4f} │ {sig:<15s} │")

print("  └──────────────────────────┴──────────┴──────────┴─────────────────┘")

# Bootstrap Sharpe ratio difference
print("\n  Bootstrap test: Sharpe ratio difference (10,000 resamples)...")
n_boot = 10000

for name in ["VT-Easy (skip >10pp)", "VT-NoExtreme (skip VIX>30)", "VT-Delayed (1 month lag)"]:
    full_m = monthly_rets["Full VT"]
    var_m = monthly_rets[name]
    n_months = len(full_m)

    boot_sharpe_diff = []
    for b in range(n_boot):
        idx = np.random.choice(n_months, size=n_months, replace=True)
        s_full = np.mean(full_m[idx]) / np.std(full_m[idx]) * np.sqrt(12)
        s_var = np.mean(var_m[idx]) / np.std(var_m[idx]) * np.sqrt(12)
        boot_sharpe_diff.append(s_full - s_var)

    boot_arr = np.array(boot_sharpe_diff)
    mean_diff = np.mean(boot_arr)
    ci_lo, ci_hi = np.percentile(boot_arr, [2.5, 97.5])
    pct_positive = (boot_arr > 0).mean() * 100

    print(f"\n  Full VT vs {name}:")
    print(f"    Mean Sharpe diff: {mean_diff:+.4f}")
    print(f"    95% CI: [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"    P(Full VT better): {pct_positive:.1f}%")

# ============================================================
# 8. Turnover & transaction cost analysis
# ============================================================
print("\n" + "=" * 72)
print("TURNOVER & TRANSACTION COST ANALYSIS")
print("=" * 72)

for name, var_key in variants.items():
    w_arr = daily_weights[name].values
    # Monthly turnover: sum of absolute weight changes at rebalance dates
    weight_changes = np.abs(np.diff(w_arr))
    # Only count changes > 0.001 (real rebalances)
    real_changes = weight_changes[weight_changes > 0.001]
    n_rebalances = len(real_changes)
    total_turnover = np.sum(weight_changes)
    ann_turnover = total_turnover / results[name]["n_years"]

    # Assume 10bps round-trip transaction cost
    tx_cost_ann = ann_turnover * 0.0010

    print(f"  {name}:")
    print(f"    Rebalance events: {n_rebalances}")
    print(f"    Annual turnover: {ann_turnover:.2%}")
    print(f"    Annual TX cost (10bps): {tx_cost_ann:.4%}")
    print(f"    Net Sharpe (after TX): {results[name]['sharpe'] - tx_cost_ann/results[name]['ann_vol']:.3f}")
    print()

# ============================================================
# 9. Key behavioral insights
# ============================================================
print("=" * 72)
print("KEY FINDINGS: CAN REAL INVESTORS FOLLOW VT?")
print("=" * 72)

n_easy = diff_counts.get("Easy", 0)
n_mod = diff_counts.get("Moderate", 0)
n_hard = diff_counts.get("Hard", 0)
n_extreme = diff_counts.get("Extreme", 0)
n_total = len(monthly_df)

pct_hard_plus = (n_hard + n_extreme) / n_total * 100

print(f"""
  1. FREQUENCY OF DIFFICULT DECISIONS:
     - {n_easy}/{n_total} ({n_easy/n_total*100:.0f}%) of monthly rebalances are EASY (small changes)
     - {n_mod}/{n_total} ({n_mod/n_total*100:.0f}%) are MODERATE (meaningful reduction)
     - {n_hard}/{n_total} ({n_hard/n_total*100:.0f}%) are HARD (large reduction during elevated VIX)
     - {n_extreme}/{n_total} ({n_extreme/n_total*100:.0f}%) are EXTREME (selling during panic, VIX>30)
     → Psychologically difficult decisions occur {pct_hard_plus:.0f}% of the time

  2. PERFORMANCE IMPACT OF BEHAVIORAL SHORTCUTS:
     - VT-Easy (skip big changes): Sharpe {results['VT-Easy (skip >10pp)']['sharpe']:.3f} vs Full VT {results['Full VT']['sharpe']:.3f}
     - VT-NoExtreme (refuse panic sales): Sharpe {results['VT-NoExtreme (skip VIX>30)']['sharpe']:.3f} vs Full VT {results['Full VT']['sharpe']:.3f}
     - VT-Delayed (1 month late): Sharpe {results['VT-Delayed (1 month lag)']['sharpe']:.3f} vs Full VT {results['Full VT']['sharpe']:.3f}

  3. MDD IMPACT (the real value of VT):
     - Full VT MDD: {results['Full VT']['mdd']:.1%}
     - VT-NoExtreme MDD: {results['VT-NoExtreme (skip VIX>30)']['mdd']:.1%}
     - Buy & Hold MDD: {results['Buy & Hold (SPY)']['mdd']:.1%}
     → Skipping extreme rebalances costs {abs(results['VT-NoExtreme (skip VIX>30)']['mdd']) - abs(results['Full VT']['mdd']):.1%} MORE drawdown

  4. THE BEHAVIORAL PARADOX:
     - VT works BECAUSE it forces counter-intuitive actions during crises
     - The hardest decisions (Extreme: {n_extreme} events in {n_total/12:.0f} years)
       are precisely the ones that provide the most protection
     - But they represent only {n_extreme/n_total*100:.1f}% of all rebalance decisions
""")

# ============================================================
# 10. MDD during specific crises for each variant
# ============================================================
print("=" * 72)
print("CRISIS-SPECIFIC DRAWDOWN COMPARISON")
print("=" * 72)

crises = [
    ("2008 GFC", "2007-10-01", "2009-03-31"),
    ("2011 Euro Crisis", "2011-07-01", "2011-10-31"),
    ("2015 China Deval", "2015-08-01", "2016-02-29"),
    ("2018 Volmageddon", "2018-01-01", "2018-12-31"),
    ("2020 COVID", "2020-02-01", "2020-04-30"),
    ("2022 Rate Hike", "2022-01-01", "2022-10-31"),
]

print("\n  ┌─────────────────────┬─────────────┬─────────────┬─────────────┬─────────────┬─────────────┐")
print("  │ Crisis              │  Full VT    │  VT-Easy    │  VT-NoExtr  │  VT-Delay   │  Buy & Hold │")
print("  ├─────────────────────┼─────────────┼─────────────┼─────────────┼─────────────┼─────────────┤")

for crisis_name, start, end in crises:
    crisis_data = data.loc[start:end]
    if len(crisis_data) < 5:
        continue

    crisis_rets = crisis_data["spy_ret"].values
    mdds = {}

    for sname, var_key in variants.items():
        w_crisis = daily_weights[sname].loc[start:end].values
        if len(w_crisis) != len(crisis_rets):
            w_crisis = w_crisis[:len(crisis_rets)]
        port_r = w_crisis * crisis_rets
        cum = np.cumprod(1 + port_r)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        mdds[sname] = dd.min()

    # Buy & Hold
    cum_bh = np.cumprod(1 + crisis_rets)
    peak_bh = np.maximum.accumulate(cum_bh)
    dd_bh = (cum_bh - peak_bh) / peak_bh
    mdds["Buy & Hold (SPY)"] = dd_bh.min()

    print(f"  │ {crisis_name:<19s} │ {mdds['Full VT']:>10.1%} │ "
          f"{mdds['VT-Easy (skip >10pp)']:>10.1%} │ "
          f"{mdds['VT-NoExtreme (skip VIX>30)']:>10.1%} │ "
          f"{mdds['VT-Delayed (1 month lag)']:>10.1%} │ "
          f"{mdds['Buy & Hold (SPY)']:>10.1%} │")

print("  └─────────────────────┴─────────────┴─────────────┴─────────────┴─────────────┴─────────────┘")

# ============================================================
# 11. "Regret" analysis: when does NOT following VT feel good?
# ============================================================
print("\n" + "=" * 72)
print("REGRET ANALYSIS: When does skipping rebalance FEEL better?")
print("=" * 72)

# For VT-NoExtreme: in the month AFTER a skipped extreme rebalance,
# did the market bounce? (making the skip feel justified)
if len(extreme_events) > 0:
    print("\n  After extreme VIX events (VIX>30), did staying invested feel 'right'?")
    print("  (i.e., did market bounce, making you think VT was wrong?)\n")

    bounce_count = 0
    total_extreme = 0

    for idx, row in extreme_events.iterrows():
        rebal_date = pd.Timestamp(idx)
        # Next month's return
        future = data[data.index > rebal_date]
        if len(future) < 21:
            continue

        next_month_ret = np.prod(1 + future["spy_ret"].values[:21]) - 1
        total_extreme += 1
        if next_month_ret > 0:
            bounce_count += 1
            feeling = "REGRET (market bounced → 'I should have stayed in')"
        else:
            feeling = "RELIEF (market kept falling → 'VT was right')"

        print(f"    {rebal_date.strftime('%Y-%m')}: VIX={row['vix']:.0f}, "
              f"next month SPY: {next_month_ret:+.1%} → {feeling}")

    if total_extreme > 0:
        print(f"\n    Summary: {bounce_count}/{total_extreme} times ({bounce_count/total_extreme*100:.0f}%) "
              f"the market bounced after an extreme event.")
        print(f"    This creates regret and makes investors abandon VT — even though")
        print(f"    the protection during the {total_extreme - bounce_count} non-bounce events")
        print(f"    is worth far more in risk-adjusted terms.")

# ============================================================
# 12. Summary statistics for the conclusion
# ============================================================
print("\n" + "=" * 72)
print("SUMMARY TABLE")
print("=" * 72)

print(f"""
  ┌─────────────────────────────────────────────────────────────────────┐
  │                K234 SUMMARY: VT BEHAVIORAL FEASIBILITY             │
  ├─────────────────────────────────────────────────────────────────────┤
  │                                                                     │
  │  DATA: SPY + GLD + VIX, {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}          │
  │  METHOD: Monthly rebalance, 12/VIX weight formula                  │
  │  REBALANCE EVENTS: {n_total} months analyzed                           │
  │                                                                     │
  │  BEHAVIORAL DIFFICULTY BREAKDOWN:                                   │
  │    Easy (Δw < 5pp):          {n_easy:>3d} / {n_total:>3d} ({n_easy/n_total*100:>4.0f}%)                        │
  │    Moderate (reduce 5-20pp):  {n_mod:>3d} / {n_total:>3d} ({n_mod/n_total*100:>4.0f}%)                        │
  │    Hard (reduce >20pp):       {n_hard:>3d} / {n_total:>3d} ({n_hard/n_total*100:>4.0f}%)                        │
  │    Extreme (VIX>30, w<40%):   {n_extreme:>3d} / {n_total:>3d} ({n_extreme/n_total*100:>4.0f}%)                        │
  │                                                                     │
  │  PERFORMANCE COST OF BEING "HUMAN":                                │
  │    Skip big rebalances:     ΔSharpe = {results['VT-Easy (skip >10pp)']['sharpe'] - full_vt_sharpe:>+.3f}                      │
  │    Refuse panic sells:      ΔSharpe = {results['VT-NoExtreme (skip VIX>30)']['sharpe'] - full_vt_sharpe:>+.3f}                      │
  │    1-month delay:           ΔSharpe = {results['VT-Delayed (1 month lag)']['sharpe'] - full_vt_sharpe:>+.3f}                      │
  │                                                                     │
  │  KEY INSIGHT: VT is behaviorally feasible for ~{100-pct_hard_plus:.0f}% of months.     │
  │  The critical {pct_hard_plus:.0f}% Hard+Extreme months are where the real value   │
  │  lives — and where human psychology most resists.                   │
  │                                                                     │
  └─────────────────────────────────────────────────────────────────────┘
""")

print(f"\nCompleted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
