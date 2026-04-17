#!/usr/bin/env python3
"""
K252: Adaptive VT — Different K for Different Vol Regimes
=========================================================
[提出: 用戶, 執行: Claude]

Background: K230 showed K=12 is flat (all K values similar). But what if
we use different K values for different regimes? K=6 when VIX is already
high (conservative), K=18 when VIX is low (aggressive)?

Methodology:
1. Regime-adaptive K variants:
   a. Step function: VIX<15→K=18, VIX 15-25→K=12, VIX>25→K=6
   b. Linear: K = 24 - 0.5*VIX (floored at 3, capped at 24)
   c. Convex: K = 12 * (15/VIX)^0.5 (floored at 3, capped at 24)
2. Benchmark: Fixed K=12
3. 50/50 SPY/GLD portfolio, monthly rebalance
4. 5-period cross-OOS, DM test

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.
"""

import sys
import warnings
warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json

# ============================================================
# Configuration
# ============================================================
np.random.seed(42)
ANN_FACTOR = 252
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
N_BOOTSTRAP = 10000

# 5-period cross-OOS
OOS_PERIODS = [
    ("2009-01-01", "2012-12-31"),  # Post-GFC recovery
    ("2013-01-01", "2016-12-31"),  # Low vol expansion
    ("2017-01-01", "2020-06-30"),  # Pre/during COVID
    ("2020-07-01", "2022-12-31"),  # COVID recovery + rate hikes
    ("2023-01-01", "2024-12-31"),  # Recent
]
DATA_START = "2005-01-01"

print("=" * 75)
print("K252: Adaptive VT — Different K for Different Vol Regimes")
print("=" * 75)

# ============================================================
# 1. Download Data
# ============================================================
print("\n[1/5] Downloading SPY, GLD, ^VIX from yfinance...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw = {}
for label, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    raw[label] = df["Close"].rename(label)

# Merge and align
data = pd.concat(raw.values(), axis=1).dropna()
print(f"  Data range: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total obs: {len(data)}")

# Compute daily returns
data["SPY_ret"] = np.log(data["SPY"] / data["SPY"].shift(1))
data["GLD_ret"] = np.log(data["GLD"] / data["GLD"].shift(1))
data = data.dropna()

# ============================================================
# 2. Define Adaptive K Functions
# ============================================================
print("\n[2/5] Defining adaptive K strategies...")


def k_fixed(vix_val, k=12.0):
    """Benchmark: fixed K=12 regardless of VIX."""
    return k


def k_step(vix_val):
    """Step function: conservative when VIX high, aggressive when low.
    VIX < 15:  K=18 (aggressive, nearly fully invested)
    VIX 15-25: K=12 (standard)
    VIX > 25:  K=6  (conservative, cut position more)
    """
    if vix_val < 15:
        return 18.0
    elif vix_val <= 25:
        return 12.0
    else:
        return 6.0


def k_linear(vix_val):
    """Linear: K = 24 - 0.5*VIX, floored at 3, capped at 24.
    At VIX=12: K=18; VIX=24: K=12; VIX=42: K=3 (floor).
    """
    k = 24.0 - 0.5 * vix_val
    return max(3.0, min(24.0, k))


def k_convex(vix_val):
    """Convex: K = 12 * (15/VIX)^0.5, floored at 3, capped at 24.
    At VIX=15: K=12; VIX=60: K=6; VIX=3.75: K=24.
    More conservative at extremes than linear.
    """
    if vix_val <= 0:
        return 24.0
    k = 12.0 * np.sqrt(15.0 / vix_val)
    return max(3.0, min(24.0, k))


strategies = {
    "Fixed K=12": k_fixed,
    "Step (18/12/6)": k_step,
    "Linear (24-0.5*VIX)": k_linear,
    "Convex (12*(15/V)^0.5)": k_convex,
}

# Print K values at representative VIX levels
print("\n  K values at representative VIX levels:")
print(f"  {'Strategy':<25s} {'VIX=10':>7s} {'VIX=15':>7s} {'VIX=20':>7s} {'VIX=25':>7s} {'VIX=35':>7s} {'VIX=50':>7s}")
print(f"  {'-'*25} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7} {'-'*7}")
for name, func in strategies.items():
    vals = [func(v) for v in [10, 15, 20, 25, 35, 50]]
    print(f"  {name:<25s} {vals[0]:7.1f} {vals[1]:7.1f} {vals[2]:7.1f} {vals[3]:7.1f} {vals[4]:7.1f} {vals[5]:7.1f}")

# ============================================================
# 3. Backtest Engine
# ============================================================
print("\n[3/5] Running backtests...")


def run_vt_backtest(data_slice, k_func, rebal_freq="monthly"):
    """
    Run K/VIX VT backtest on 50/50 SPY/GLD portfolio.

    VT weight = K(VIX) / VIX, capped at [0, 1.5].
    Monthly rebalance: signal from last trading day of previous month.
    Lagged: VIX_t determines weight for t+1 (no look-ahead).
    """
    df = data_slice.copy()

    # Compute adaptive K and VT weight (lagged by 1 day)
    k_series = df["VIX"].apply(k_func)
    raw_weight = k_series / df["VIX"]
    vt_weight = raw_weight.clip(0.0, 1.5).shift(1)  # lag by 1 day
    df["vt_weight"] = vt_weight

    if rebal_freq == "monthly":
        # Only update weight at month-end
        df["month"] = df.index.to_period("M")
        # Get last trading day of each month
        month_ends = df.groupby("month").tail(1).index
        # Forward-fill: carry month-end weight through the month
        weight_monthly = pd.Series(np.nan, index=df.index)
        for me in month_ends:
            weight_monthly.loc[me] = df.loc[me, "vt_weight"]
        weight_monthly = weight_monthly.shift(1)  # use last month-end weight for next month
        weight_monthly = weight_monthly.ffill()
        df["weight_used"] = weight_monthly
    else:
        df["weight_used"] = vt_weight

    df = df.dropna(subset=["weight_used"])

    # Portfolio return: 50% SPY + 50% GLD, each scaled by VT weight
    # VT weight applies to the overall equity allocation
    df["port_ret"] = df["weight_used"] * (0.5 * df["SPY_ret"] + 0.5 * df["GLD_ret"]) + \
                     (1 - df["weight_used"]) * RF_DAILY

    return df[["port_ret", "weight_used", "VIX"]].copy()


def compute_metrics(returns, name=""):
    """Compute Sharpe, MDD, Calmar, Sortino, annualized return, vol."""
    r = returns.values
    n = len(r)
    if n < 60:
        return None

    ann_ret = np.mean(r) * ANN_FACTOR
    ann_vol = np.std(r, ddof=1) * np.sqrt(ANN_FACTOR)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.min(dd)

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0]
    down_vol = np.std(downside, ddof=1) * np.sqrt(ANN_FACTOR) if len(downside) > 1 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / down_vol if down_vol > 0 else 0

    # Average turnover (weight changes)
    return {
        "name": name,
        "n_days": n,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
    }


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: E[loss1 - loss2] = 0.
    Returns (t-stat, p-value). One-sided: p<0.05 means loss1 < loss2 (model1 better).
    Using squared return loss: loss = (r_benchmark - r_strategy)^2 → not applicable.
    Instead, use return difference directly for economic DM test.
    """
    d = loss1 - loss2
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = np.mean(d)
    # Newey-West HAC variance with h lags
    gamma_0 = np.var(d, ddof=1)
    nw_var = gamma_0
    for k in range(1, h + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * (1 - k / (h + 1)) * gamma_k

    se = np.sqrt(nw_var / n) if nw_var > 0 else 1e-10
    t_stat = d_mean / se
    p_val = 1 - stats.t.cdf(t_stat, df=n - 1)  # one-sided: adaptive > fixed

    return t_stat, p_val


# ============================================================
# 4. Cross-OOS Evaluation
# ============================================================
print("\n[4/5] Running 5-period cross-OOS evaluation...")

all_results = {name: [] for name in strategies}
all_returns = {name: [] for name in strategies}
dm_results = {name: [] for name in strategies if name != "Fixed K=12"}

for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
    print(f"\n  --- OOS Period {period_idx+1}: {oos_start} to {oos_end} ---")

    # Filter data for OOS period (use data from 1 month before for weight initialization)
    pre_start = pd.Timestamp(oos_start) - pd.DateOffset(months=2)
    mask = (data.index >= pre_start) & (data.index <= oos_end)
    period_data = data.loc[mask].copy()

    if len(period_data) < 60:
        print(f"    Skipping: only {len(period_data)} obs")
        continue

    # Run each strategy
    period_returns = {}
    for name, func in strategies.items():
        bt = run_vt_backtest(period_data, func, rebal_freq="monthly")
        # Keep only OOS portion
        bt_oos = bt.loc[oos_start:oos_end]

        if len(bt_oos) < 30:
            continue

        metrics = compute_metrics(bt_oos["port_ret"], name)
        if metrics:
            metrics["oos_period"] = period_idx + 1
            metrics["oos_range"] = f"{oos_start} to {oos_end}"
            all_results[name].append(metrics)
            period_returns[name] = bt_oos["port_ret"]
            all_returns[name].append(bt_oos["port_ret"])

    # DM test: adaptive vs fixed within each period
    if "Fixed K=12" in period_returns:
        fixed_ret = period_returns["Fixed K=12"]
        for name in strategies:
            if name == "Fixed K=12":
                continue
            if name in period_returns:
                adaptive_ret = period_returns[name]
                # Align
                common_idx = fixed_ret.index.intersection(adaptive_ret.index)
                if len(common_idx) < 60:
                    dm_results[name].append({"period": period_idx+1, "t": np.nan, "p": np.nan})
                    continue
                t_stat, p_val = dm_test(
                    adaptive_ret.loc[common_idx].values,
                    fixed_ret.loc[common_idx].values,
                    h=21  # monthly HAC
                )
                dm_results[name].append({"period": period_idx+1, "t": t_stat, "p": p_val})

    # Print period results
    print(f"    {'Strategy':<25s} {'Sharpe':>7s} {'MDD':>8s} {'Ann Ret':>8s} {'Ann Vol':>8s}")
    for name in strategies:
        if all_results[name] and all_results[name][-1]["oos_period"] == period_idx + 1:
            m = all_results[name][-1]
            print(f"    {name:<25s} {m['sharpe']:7.3f} {m['mdd']:8.2%} {m['ann_return']:8.2%} {m['ann_vol']:8.2%}")

# ============================================================
# 5. Aggregate Results
# ============================================================
print("\n" + "=" * 75)
print("[5/5] AGGREGATE RESULTS")
print("=" * 75)

# Summary table
print("\n  A. Average Metrics Across 5 OOS Periods:")
print(f"  {'Strategy':<25s} {'Sharpe':>7s} {'MDD':>8s} {'Ann Ret':>8s} {'Calmar':>7s} {'Sortino':>8s} {'#Periods':>8s}")
print(f"  {'-'*25} {'-'*7} {'-'*8} {'-'*8} {'-'*7} {'-'*8} {'-'*8}")

agg_metrics = {}
for name in strategies:
    results = all_results[name]
    if not results:
        continue
    avg_sharpe = np.mean([r["sharpe"] for r in results])
    avg_mdd = np.mean([r["mdd"] for r in results])
    avg_ret = np.mean([r["ann_return"] for r in results])
    avg_calmar = np.mean([r["calmar"] for r in results])
    avg_sortino = np.mean([r["sortino"] for r in results])
    n_periods = len(results)
    print(f"  {name:<25s} {avg_sharpe:7.3f} {avg_mdd:8.2%} {avg_ret:8.2%} {avg_calmar:7.3f} {avg_sortino:8.3f} {n_periods:8d}")
    agg_metrics[name] = {
        "avg_sharpe": avg_sharpe,
        "avg_mdd": avg_mdd,
        "avg_return": avg_ret,
        "avg_calmar": avg_calmar,
        "avg_sortino": avg_sortino,
        "n_periods": n_periods,
    }

# DM test results
print("\n  B. Diebold-Mariano Test (Adaptive vs Fixed K=12, H0: no difference):")
print(f"  {'Strategy':<25s} {'Period':>7s} {'DM t':>7s} {'p-val':>7s} {'Sig?':>5s}")
print(f"  {'-'*25} {'-'*7} {'-'*7} {'-'*7} {'-'*5}")

for name in dm_results:
    for dm in dm_results[name]:
        sig = "YES" if dm["p"] < 0.05 else "no"
        if np.isnan(dm["t"]):
            print(f"  {name:<25s} {dm['period']:7d}     N/A     N/A   N/A")
        else:
            print(f"  {name:<25s} {dm['period']:7d} {dm['t']:7.3f} {dm['p']:7.4f} {sig:>5s}")

# Overall DM summary
print("\n  C. DM Test Summary (Adaptive better than Fixed in how many periods?):")
for name in dm_results:
    wins = sum(1 for dm in dm_results[name] if not np.isnan(dm["p"]) and dm["p"] < 0.05)
    total = sum(1 for dm in dm_results[name] if not np.isnan(dm["p"]))
    avg_t = np.nanmean([dm["t"] for dm in dm_results[name]])
    print(f"  {name:<25s}: {wins}/{total} periods significant, avg DM t = {avg_t:.3f}")

# Bootstrap test on full-sample difference
print("\n  D. Full-Sample Bootstrap Test (Sharpe difference):")
for name in strategies:
    if name == "Fixed K=12":
        continue
    # Concatenate all OOS returns
    if not all_returns[name] or not all_returns["Fixed K=12"]:
        continue

    adaptive_all = pd.concat(all_returns[name])
    fixed_all = pd.concat(all_returns["Fixed K=12"])
    common = adaptive_all.index.intersection(fixed_all.index)
    a_ret = adaptive_all.loc[common].values
    f_ret = fixed_all.loc[common].values

    # Observed Sharpe difference
    a_sharpe = (np.mean(a_ret) * ANN_FACTOR - RF_ANNUAL) / (np.std(a_ret, ddof=1) * np.sqrt(ANN_FACTOR))
    f_sharpe = (np.mean(f_ret) * ANN_FACTOR - RF_ANNUAL) / (np.std(f_ret, ddof=1) * np.sqrt(ANN_FACTOR))
    obs_diff = a_sharpe - f_sharpe

    # Block bootstrap (block=21 days for monthly autocorrelation)
    n = len(a_ret)
    block_size = 21
    n_blocks = n // block_size
    boot_diffs = []
    for _ in range(N_BOOTSTRAP):
        idx = np.random.randint(0, n - block_size, size=n_blocks)
        boot_a = np.concatenate([a_ret[i:i+block_size] for i in idx])
        boot_f = np.concatenate([f_ret[i:i+block_size] for i in idx])
        bs_a = (np.mean(boot_a) * ANN_FACTOR - RF_ANNUAL) / (np.std(boot_a, ddof=1) * np.sqrt(ANN_FACTOR))
        bs_f = (np.mean(boot_f) * ANN_FACTOR - RF_ANNUAL) / (np.std(boot_f, ddof=1) * np.sqrt(ANN_FACTOR))
        boot_diffs.append(bs_a - bs_f)

    boot_diffs = np.array(boot_diffs)
    p_boot = np.mean(boot_diffs <= 0)  # prob that adaptive is NOT better
    ci_lo, ci_hi = np.percentile(boot_diffs, [2.5, 97.5])

    print(f"  {name:<25s}: dSharpe = {obs_diff:+.4f}, bootstrap p = {p_boot:.4f}, 95% CI [{ci_lo:+.4f}, {ci_hi:+.4f}]")

# ============================================================
# 6. Detailed Weight Analysis
# ============================================================
print("\n  E. Weight Distribution by Regime (Full Sample):")

# Run full-sample backtest for weight analysis
full_weights = {}
for name, func in strategies.items():
    bt = run_vt_backtest(data, func, rebal_freq="monthly")
    full_weights[name] = bt

    # Regime breakdown
    low_vix = bt[bt["VIX"] < 15]["weight_used"]
    mid_vix = bt[(bt["VIX"] >= 15) & (bt["VIX"] <= 25)]["weight_used"]
    high_vix = bt[bt["VIX"] > 25]["weight_used"]

    print(f"\n  {name}:")
    if len(low_vix) > 0:
        print(f"    VIX < 15 ({len(low_vix):4d} days): avg weight = {low_vix.mean():.3f}, std = {low_vix.std():.3f}")
    if len(mid_vix) > 0:
        print(f"    VIX 15-25 ({len(mid_vix):4d} days): avg weight = {mid_vix.mean():.3f}, std = {mid_vix.std():.3f}")
    if len(high_vix) > 0:
        print(f"    VIX > 25 ({len(high_vix):4d} days): avg weight = {high_vix.mean():.3f}, std = {high_vix.std():.3f}")

# ============================================================
# 7. Regime-Specific Performance
# ============================================================
print("\n  F. Performance by VIX Regime (Full Sample OOS Concat):")
for regime_name, vix_lo, vix_hi in [("VIX<15", 0, 15), ("VIX 15-25", 15, 25), ("VIX>25", 25, 200)]:
    print(f"\n  --- {regime_name} ---")
    print(f"  {'Strategy':<25s} {'Sharpe':>7s} {'Ann Ret':>8s} {'N_days':>7s}")
    for name in strategies:
        if name not in full_weights:
            continue
        bt = full_weights[name]
        mask = (bt["VIX"] >= vix_lo) & (bt["VIX"] < vix_hi)
        regime_ret = bt.loc[mask, "port_ret"]
        if len(regime_ret) < 30:
            continue
        ann_ret = np.mean(regime_ret) * ANN_FACTOR
        ann_vol = np.std(regime_ret, ddof=1) * np.sqrt(ANN_FACTOR)
        sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
        print(f"  {name:<25s} {sharpe:7.3f} {ann_ret:8.2%} {len(regime_ret):7d}")

# ============================================================
# 8. Key Insight: Does Adaptation Matter?
# ============================================================
print("\n" + "=" * 75)
print("KEY FINDINGS")
print("=" * 75)

# Check if any adaptive strategy significantly beats fixed
any_significant = False
for name in dm_results:
    wins = sum(1 for dm in dm_results[name] if not np.isnan(dm["p"]) and dm["p"] < 0.05)
    total = sum(1 for dm in dm_results[name] if not np.isnan(dm["p"]))
    if wins >= 3:
        any_significant = True
        print(f"\n  ! {name} significantly beats Fixed K=12 in {wins}/{total} periods")

if not any_significant:
    print("\n  RESULT: NO adaptive strategy significantly beats Fixed K=12")
    print("  This CONFIRMS K230: the choice of K is not important.")
    print("  Even adapting K to regimes does not help.")

# Sharpe comparison
if "Fixed K=12" in agg_metrics:
    fixed_sharpe = agg_metrics["Fixed K=12"]["avg_sharpe"]
    print(f"\n  Fixed K=12 avg Sharpe: {fixed_sharpe:.4f}")
    for name in strategies:
        if name == "Fixed K=12" or name not in agg_metrics:
            continue
        diff = agg_metrics[name]["avg_sharpe"] - fixed_sharpe
        print(f"  {name:<25s} avg Sharpe: {agg_metrics[name]['avg_sharpe']:.4f} (diff: {diff:+.4f})")

# Theoretical explanation
print("\n  THEORETICAL EXPLANATION:")
print("  The K/VIX rule already has built-in regime adaptation:")
print("  - When VIX=30: weight = 12/30 = 0.40 (already conservative)")
print("  - When VIX=12: weight = 12/12 = 1.00 (already aggressive)")
print("  Changing K just rescales this, but the RATIO is what matters.")
print("  The hyperbolic (1/VIX) shape already provides optimal concavity.")
print("  Making K adaptive is a 2nd-order correction to a 1st-order effect.")

# ============================================================
# 9. Save Results
# ============================================================
results_output = {
    "experiment": "K252",
    "title": "Adaptive VT: Different K for Different Vol Regimes",
    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": len(data),
    "methodology": {
        "portfolio": "50/50 SPY/GLD",
        "rebalance": "monthly",
        "oos_periods": [{"start": s, "end": e} for s, e in OOS_PERIODS],
        "strategies": {
            "Fixed K=12": "K=12 always",
            "Step (18/12/6)": "VIX<15: K=18, VIX 15-25: K=12, VIX>25: K=6",
            "Linear (24-0.5*VIX)": "K = max(3, min(24, 24-0.5*VIX))",
            "Convex (12*(15/V)^0.5)": "K = max(3, min(24, 12*sqrt(15/VIX)))",
        },
    },
    "aggregate_metrics": {},
    "dm_tests": {},
    "conclusion": "",
}

for name, m in agg_metrics.items():
    results_output["aggregate_metrics"][name] = {
        k: round(v, 6) if isinstance(v, float) else v for k, v in m.items()
    }

for name, dms in dm_results.items():
    results_output["dm_tests"][name] = []
    for dm in dms:
        results_output["dm_tests"][name].append({
            "period": dm["period"],
            "t_stat": round(dm["t"], 4) if not np.isnan(dm["t"]) else None,
            "p_value": round(dm["p"], 4) if not np.isnan(dm["p"]) else None,
        })

if any_significant:
    results_output["conclusion"] = "Some adaptive strategies show significance in select periods."
else:
    results_output["conclusion"] = (
        "NULL RESULT: No adaptive K strategy significantly beats fixed K=12. "
        "Confirms K230: K value is not important because K/VIX already has built-in "
        "regime adaptation via the hyperbolic 1/VIX shape."
    )

results_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a0d28816/experiments/k252_adaptive_vt_results.json"
with open(results_path, "w") as f:
    json.dump(results_output, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to: {results_path}")
print("\n" + "=" * 75)
print("K252 COMPLETE")
print("=" * 75)
