"""
K646: Cross-OOS Validation of 80/20 vs 50/50 SPY/GLD with 12/VIX Overlay
=========================================================================
[提出: Claude, 執行: Claude]

Background:
  K645 found that with 12/VIX overlay, optimal GLD weight shifts from 50% to 20%
  (Sharpe 1.71 vs 1.40). This is a full-sample result and may be period-specific.

  This experiment performs rigorous cross-OOS validation across 5 non-overlapping
  periods covering diverse market conditions (GFC, recovery, low-vol bull, COVID,
  tariff uncertainty).

Strategies tested:
  - 100/0 SPY/GLD + 12/VIX (no GLD)
  - 80/20 SPY/GLD + 12/VIX (K645 optimal)
  - 70/30 SPY/GLD + 12/VIX
  - 60/40 SPY/GLD + 12/VIX
  - 50/50 SPY/GLD + 12/VIX (current recommendation)

OOS periods:
  - OOS1: 2008-01 to 2009-12 (GFC)
  - OOS2: 2011-01 to 2013-12 (post-GFC recovery + gold bear)
  - OOS3: 2015-01 to 2017-12 (low vol bull)
  - OOS4: 2020-01 to 2021-12 (COVID + recovery)
  - OOS5: 2023-01 to 2024-12 (tariff uncertainty + gold rally)

Robustness criteria:
  - Must win 4/5 OOS periods for "robust"
  - Average Sharpe across all 5 periods
  - Worst-case Sharpe (minimax criterion)
  - Bootstrap significance test in each period

Data: yfinance SPY, GLD, ^VIX daily (2006-01-01 to 2026-03-27)

References:
  - Baur & Lucey (2010), "Is Gold a Hedge or a Safe Haven?", JBF
  - Baur & McDermott (2010), "Is gold a safe haven? International evidence", JBF
  - Erb & Harvey (2013), "The Golden Dilemma", FAJ
  - Harvey et al. (2016), "...and the Cross-Section of Expected Returns", RFS
  - K645 results: optimal GLD weight = 20% with 12/VIX (full sample)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2006-01-01"
DATA_END = "2026-03-27"
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

VIX_TARGET = 12.0  # 12/VIX allocation
TX_COST_BPS = 2    # 2bp per trade

N_BOOTSTRAP = 10000
RANDOM_SEED = 42

# Strategy definitions: (name, spy_weight, gld_weight)
STRATEGIES = [
    ("100/0 SPY/GLD + 12/VIX", 1.0, 0.0),
    ("80/20 SPY/GLD + 12/VIX", 0.8, 0.2),
    ("70/30 SPY/GLD + 12/VIX", 0.7, 0.3),
    ("60/40 SPY/GLD + 12/VIX", 0.6, 0.4),
    ("50/50 SPY/GLD + 12/VIX", 0.5, 0.5),
]

# OOS periods
OOS_PERIODS = [
    ("OOS1_GFC", "2008-01-01", "2009-12-31"),
    ("OOS2_Recovery", "2011-01-01", "2013-12-31"),
    ("OOS3_LowVol", "2015-01-01", "2017-12-31"),
    ("OOS4_COVID", "2020-01-01", "2021-12-31"),
    ("OOS5_Tariff", "2023-01-01", "2024-12-31"),
]

print("=" * 80)
print("K646: Cross-OOS Validation — 80/20 vs 50/50 SPY/GLD + 12/VIX")
print("[提出: Claude, 執行: Claude]")
print("=" * 80)

# ==================================================================
# 1. DATA DOWNLOAD
# ==================================================================
print("\n[1] Downloading data...")
tickers = ["SPY", "GLD", "^VIX"]
raw = yf.download(tickers, start=DATA_START, end=DATA_END, auto_adjust=True)

prices = pd.DataFrame()
for t in tickers:
    col_name = t.replace("^", "")
    try:
        prices[col_name] = raw["Close"][t]
    except KeyError:
        prices[col_name] = raw[("Close", t)]

prices = prices.dropna()
print(f"  Data: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(prices)}")

# Returns
ret = prices[["SPY", "GLD"]].pct_change().dropna()
vix = prices["VIX"].reindex(ret.index)

print(f"  Return series: {len(ret)} days")

# ==================================================================
# 2. HELPER FUNCTIONS
# ==================================================================

def apply_12vix(risky_ret, vix_series, rf_daily=RF_DAILY):
    """Apply 12/VIX allocation with proper lag — signal from t-1, return at t.

    2026-05-06 K547-family lookahead patch. Same fix as K645 sibling.
    """
    equity_weight_raw = np.minimum(VIX_TARGET / vix_series, 1.0)
    equity_weight = equity_weight_raw.shift(1).fillna(equity_weight_raw.iloc[0])
    portfolio_ret = equity_weight * risky_ret + (1 - equity_weight) * rf_daily
    return portfolio_ret, equity_weight


def calc_metrics(ret_series, name="", tx_cost_bps=0, weight_changes=None):
    """Calculate key portfolio metrics with optional TX costs."""
    if len(ret_series) < 20:
        return {
            "name": name, "cagr_pct": np.nan, "ann_vol_pct": np.nan,
            "sharpe": np.nan, "net_sharpe": np.nan, "sortino": np.nan,
            "calmar": np.nan, "max_dd_pct": np.nan, "total_return_pct": np.nan,
            "n_days": len(ret_series)
        }

    # Net returns (subtract TX costs)
    net_ret = ret_series.copy()
    if tx_cost_bps > 0 and weight_changes is not None:
        tx_drag = weight_changes.abs() * (tx_cost_bps / 10000)
        net_ret = ret_series - tx_drag

    cum = (1 + ret_series).cumprod()
    cum_net = (1 + net_ret).cumprod()
    n_years = len(ret_series) / 252

    cagr = cum.iloc[-1] ** (1 / n_years) - 1
    cagr_net = cum_net.iloc[-1] ** (1 / n_years) - 1
    ann_vol = ret_series.std() * np.sqrt(252)

    sharpe = (cagr - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
    net_sharpe = (cagr_net - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    max_dd = drawdown.min()

    # Sortino
    downside = ret_series[ret_series < 0].std() * np.sqrt(252)
    sortino = (cagr - RF_ANNUAL) / downside if downside > 0 else 0

    # Calmar
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    return {
        "name": name,
        "cagr_pct": round(float(cagr * 100), 2),
        "ann_vol_pct": round(float(ann_vol * 100), 2),
        "sharpe": round(float(sharpe), 3),
        "net_sharpe": round(float(net_sharpe), 3),
        "sortino": round(float(sortino), 3),
        "calmar": round(float(calmar), 3),
        "max_dd_pct": round(float(max_dd * 100), 1),
        "total_return_pct": round(float((cum.iloc[-1] - 1) * 100), 1),
        "n_days": int(len(ret_series))
    }


def build_strategy_returns(spy_ret, gld_ret, vix_series, w_spy, w_gld):
    """Build strategy returns with 12/VIX overlay."""
    # Underlying risky portfolio return (SPY/GLD blend)
    risky_ret = w_spy * spy_ret + w_gld * gld_ret

    # Apply 12/VIX overlay
    port_ret, eq_weight = apply_12vix(risky_ret, vix_series)

    # Weight changes for TX cost calculation
    weight_changes = eq_weight.diff().fillna(0)

    return port_ret, eq_weight, weight_changes


def bootstrap_sharpe_diff(ret_a, ret_b, n_boot=N_BOOTSTRAP, seed=RANDOM_SEED):
    """Bootstrap test for Sharpe ratio difference between two strategies."""
    rng = np.random.RandomState(seed)
    n = len(ret_a)

    sharpe_a = (ret_a.mean() * 252 - RF_ANNUAL) / (ret_a.std() * np.sqrt(252))
    sharpe_b = (ret_b.mean() * 252 - RF_ANNUAL) / (ret_b.std() * np.sqrt(252))
    obs_diff = sharpe_a - sharpe_b

    boot_diffs = np.zeros(n_boot)
    ret_a_vals = ret_a.values
    ret_b_vals = ret_b.values

    for i in range(n_boot):
        idx = rng.randint(0, n, size=n)
        boot_a = ret_a_vals[idx]
        boot_b = ret_b_vals[idx]

        s_a = (boot_a.mean() * 252 - RF_ANNUAL) / (boot_a.std() * np.sqrt(252))
        s_b = (boot_b.mean() * 252 - RF_ANNUAL) / (boot_b.std() * np.sqrt(252))
        boot_diffs[i] = s_a - s_b

    # Two-sided p-value
    p_value = 2 * min(
        np.mean(boot_diffs <= 0),
        np.mean(boot_diffs >= 0)
    )

    ci_lower = np.percentile(boot_diffs, 2.5)
    ci_upper = np.percentile(boot_diffs, 97.5)

    return {
        "obs_sharpe_diff": round(float(obs_diff), 4),
        "mean_boot_diff": round(float(np.mean(boot_diffs)), 4),
        "ci_95_lower": round(float(ci_lower), 4),
        "ci_95_upper": round(float(ci_upper), 4),
        "p_value": round(float(p_value), 4),
        "significant_5pct": bool(p_value < 0.05),
        "significant_10pct": bool(p_value < 0.10)
    }


# ==================================================================
# 3. CROSS-OOS ANALYSIS
# ==================================================================
print("\n[3] Running Cross-OOS Analysis...")
print("=" * 80)

oos_results = {}
all_strategy_oos_sharpes = {s[0]: [] for s in STRATEGIES}
all_strategy_oos_net_sharpes = {s[0]: [] for s in STRATEGIES}

for oos_name, oos_start, oos_end in OOS_PERIODS:
    print(f"\n--- {oos_name}: {oos_start} to {oos_end} ---")

    # Filter data for this OOS period
    mask = (ret.index >= oos_start) & (ret.index <= oos_end)
    r_oos = ret[mask]
    v_oos = vix[mask]

    if len(r_oos) < 20:
        print(f"  WARNING: Only {len(r_oos)} days, skipping")
        continue

    print(f"  Days: {len(r_oos)}")
    print(f"  SPY return: {r_oos['SPY'].sum()*100:.1f}%")
    print(f"  GLD return: {r_oos['GLD'].sum()*100:.1f}%")
    print(f"  Avg VIX: {v_oos.mean():.1f}")

    period_results = {
        "period": oos_name,
        "start": oos_start,
        "end": oos_end,
        "n_days": int(len(r_oos)),
        "avg_vix": round(float(v_oos.mean()), 1),
        "spy_total_ret_pct": round(float((1 + r_oos["SPY"]).prod() - 1) * 100, 1),
        "gld_total_ret_pct": round(float((1 + r_oos["GLD"]).prod() - 1) * 100, 1),
        "strategies": {}
    }

    for strat_name, w_spy, w_gld in STRATEGIES:
        port_ret, eq_weight, weight_changes = build_strategy_returns(
            r_oos["SPY"], r_oos["GLD"], v_oos, w_spy, w_gld
        )

        m = calc_metrics(port_ret, strat_name, TX_COST_BPS, weight_changes)
        period_results["strategies"][strat_name] = m

        all_strategy_oos_sharpes[strat_name].append(m["sharpe"])
        all_strategy_oos_net_sharpes[strat_name].append(m["net_sharpe"])

        print(f"  {strat_name}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr_pct']:.1f}%, "
              f"MDD={m['max_dd_pct']:.1f}%, Net Sharpe={m['net_sharpe']:.3f}")

    # Bootstrap tests: 80/20 vs 50/50 and others vs 50/50
    port_5050, _, _ = build_strategy_returns(
        r_oos["SPY"], r_oos["GLD"], v_oos, 0.5, 0.5
    )

    period_results["pairwise_tests_vs_5050"] = {}
    for strat_name, w_spy, w_gld in STRATEGIES:
        if strat_name == "50/50 SPY/GLD + 12/VIX":
            continue
        port_strat, _, _ = build_strategy_returns(
            r_oos["SPY"], r_oos["GLD"], v_oos, w_spy, w_gld
        )
        test = bootstrap_sharpe_diff(port_strat, port_5050)
        period_results["pairwise_tests_vs_5050"][strat_name] = test
        sig_str = "***" if test["significant_5pct"] else ("*" if test["significant_10pct"] else "")
        print(f"    {strat_name} vs 50/50: diff={test['obs_sharpe_diff']:.3f} "
              f"[{test['ci_95_lower']:.3f}, {test['ci_95_upper']:.3f}] p={test['p_value']:.3f} {sig_str}")

    oos_results[oos_name] = period_results


# ==================================================================
# 4. CROSS-OOS ROBUSTNESS SUMMARY
# ==================================================================
print("\n\n" + "=" * 80)
print("[4] CROSS-OOS ROBUSTNESS SUMMARY")
print("=" * 80)

# Benchmark: 50/50
benchmark = "50/50 SPY/GLD + 12/VIX"
benchmark_sharpes = all_strategy_oos_sharpes[benchmark]

robustness_summary = {}

for strat_name, w_spy, w_gld in STRATEGIES:
    if strat_name == benchmark:
        continue

    sharpes = all_strategy_oos_sharpes[strat_name]
    net_sharpes = all_strategy_oos_net_sharpes[strat_name]

    # Win count vs benchmark
    wins = sum(1 for s, b in zip(sharpes, benchmark_sharpes) if s > b)
    losses = sum(1 for s, b in zip(sharpes, benchmark_sharpes) if s < b)
    ties = len(sharpes) - wins - losses

    avg_sharpe = np.mean(sharpes)
    worst_sharpe = min(sharpes)
    best_sharpe = max(sharpes)
    avg_net_sharpe = np.mean(net_sharpes)

    # Avg Sharpe difference vs benchmark
    diffs = [s - b for s, b in zip(sharpes, benchmark_sharpes)]
    avg_diff = np.mean(diffs)

    # Consistent? (4/5 wins = robust)
    is_robust = wins >= 4

    summary = {
        "strategy": strat_name,
        "oos_sharpes": [round(s, 3) for s in sharpes],
        "avg_sharpe": round(float(avg_sharpe), 3),
        "worst_sharpe": round(float(worst_sharpe), 3),
        "best_sharpe": round(float(best_sharpe), 3),
        "avg_net_sharpe": round(float(avg_net_sharpe), 3),
        "wins_vs_5050": wins,
        "losses_vs_5050": losses,
        "ties_vs_5050": ties,
        "avg_sharpe_diff_vs_5050": round(float(avg_diff), 3),
        "is_robust_4of5": is_robust,
        "oos_periods_won": [],
        "oos_periods_lost": []
    }

    for i, (oos_name, _, _) in enumerate(OOS_PERIODS):
        if sharpes[i] > benchmark_sharpes[i]:
            summary["oos_periods_won"].append(oos_name)
        elif sharpes[i] < benchmark_sharpes[i]:
            summary["oos_periods_lost"].append(oos_name)

    robustness_summary[strat_name] = summary

    print(f"\n  {strat_name}:")
    print(f"    Wins vs 50/50: {wins}/{len(sharpes)} {'✓ ROBUST' if is_robust else '✗ NOT ROBUST'}")
    print(f"    Avg Sharpe: {avg_sharpe:.3f} (vs benchmark {np.mean(benchmark_sharpes):.3f})")
    print(f"    Avg diff: {avg_diff:+.3f}")
    print(f"    Worst Sharpe: {worst_sharpe:.3f}")
    print(f"    Best Sharpe: {best_sharpe:.3f}")
    print(f"    Won: {summary['oos_periods_won']}")
    print(f"    Lost: {summary['oos_periods_lost']}")

# Also show benchmark stats
print(f"\n  BENCHMARK — {benchmark}:")
print(f"    Avg Sharpe: {np.mean(benchmark_sharpes):.3f}")
print(f"    Worst: {min(benchmark_sharpes):.3f}")
print(f"    Best: {max(benchmark_sharpes):.3f}")
print(f"    Per-period: {[round(s, 3) for s in benchmark_sharpes]}")


# ==================================================================
# 5. MINIMAX ANALYSIS (worst-case across periods)
# ==================================================================
print("\n\n" + "=" * 80)
print("[5] MINIMAX ANALYSIS — Worst-Case Performance")
print("=" * 80)

minimax = {}
for strat_name, w_spy, w_gld in STRATEGIES:
    sharpes = all_strategy_oos_sharpes[strat_name]
    worst = min(sharpes)
    worst_idx = sharpes.index(worst)
    worst_period = OOS_PERIODS[worst_idx][0]
    minimax[strat_name] = {
        "worst_sharpe": round(float(worst), 3),
        "worst_period": worst_period,
        "all_sharpes": [round(s, 3) for s in sharpes]
    }
    print(f"  {strat_name}: worst Sharpe = {worst:.3f} in {worst_period}")

# Which strategy has the best worst-case?
best_minimax = max(minimax.items(), key=lambda x: x[1]["worst_sharpe"])
print(f"\n  BEST MINIMAX: {best_minimax[0]} (worst Sharpe = {best_minimax[1]['worst_sharpe']:.3f})")


# ==================================================================
# 6. REGIME-CONDITIONAL ANALYSIS
# ==================================================================
print("\n\n" + "=" * 80)
print("[6] REGIME-CONDITIONAL ANALYSIS")
print("=" * 80)

# Classify OOS periods by average VIX
regime_analysis = {
    "high_vix_periods": [],  # avg VIX > 20
    "low_vix_periods": [],   # avg VIX <= 20
}

for oos_name, oos_start, oos_end in OOS_PERIODS:
    mask = (ret.index >= oos_start) & (ret.index <= oos_end)
    v_oos = vix[mask]
    avg_vix = v_oos.mean()

    period_data = {
        "period": oos_name,
        "avg_vix": round(float(avg_vix), 1),
    }

    for strat_name, _, _ in STRATEGIES:
        period_data[strat_name] = oos_results[oos_name]["strategies"][strat_name]["sharpe"]

    if avg_vix > 20:
        regime_analysis["high_vix_periods"].append(period_data)
    else:
        regime_analysis["low_vix_periods"].append(period_data)

print("\n  HIGH VIX periods (avg > 20):")
for p in regime_analysis["high_vix_periods"]:
    print(f"    {p['period']} (VIX={p['avg_vix']}): ", end="")
    for s, _, _ in STRATEGIES:
        print(f"{s.split('+')[0].strip()}={p[s]:.3f}  ", end="")
    print()

print("\n  LOW VIX periods (avg <= 20):")
for p in regime_analysis["low_vix_periods"]:
    print(f"    {p['period']} (VIX={p['avg_vix']}): ", end="")
    for s, _, _ in STRATEGIES:
        print(f"{s.split('+')[0].strip()}={p[s]:.3f}  ", end="")
    print()

# Average Sharpe by regime for each strategy
regime_sharpe_summary = {}
for strat_name, _, _ in STRATEGIES:
    high_sharpes = [p[strat_name] for p in regime_analysis["high_vix_periods"]]
    low_sharpes = [p[strat_name] for p in regime_analysis["low_vix_periods"]]
    regime_sharpe_summary[strat_name] = {
        "avg_sharpe_high_vix": round(float(np.mean(high_sharpes)), 3) if high_sharpes else None,
        "avg_sharpe_low_vix": round(float(np.mean(low_sharpes)), 3) if low_sharpes else None,
    }
    print(f"\n  {strat_name}:")
    if high_sharpes:
        print(f"    High VIX avg Sharpe: {np.mean(high_sharpes):.3f}")
    if low_sharpes:
        print(f"    Low VIX avg Sharpe: {np.mean(low_sharpes):.3f}")


# ==================================================================
# 7. STATISTICAL SIGNIFICANCE (AGGREGATED)
# ==================================================================
print("\n\n" + "=" * 80)
print("[7] AGGREGATED STATISTICAL TESTS")
print("=" * 80)

# Full sample bootstrap: 80/20 vs 50/50
print("\n  Full-sample bootstrap: 80/20 vs 50/50")
port_8020_full, _, _ = build_strategy_returns(ret["SPY"], ret["GLD"], vix, 0.8, 0.2)
port_5050_full, _, _ = build_strategy_returns(ret["SPY"], ret["GLD"], vix, 0.5, 0.5)
full_sample_test = bootstrap_sharpe_diff(port_8020_full, port_5050_full)
print(f"    Sharpe diff: {full_sample_test['obs_sharpe_diff']:.4f}")
print(f"    95% CI: [{full_sample_test['ci_95_lower']:.4f}, {full_sample_test['ci_95_upper']:.4f}]")
print(f"    p-value: {full_sample_test['p_value']:.4f}")
print(f"    Significant at 5%: {full_sample_test['significant_5pct']}")

# Count how many OOS periods show significance
sig_count_5pct = {}
sig_count_10pct = {}
for strat_name in robustness_summary:
    count_5 = 0
    count_10 = 0
    for oos_name in oos_results:
        tests = oos_results[oos_name].get("pairwise_tests_vs_5050", {})
        if strat_name in tests:
            if tests[strat_name]["significant_5pct"]:
                count_5 += 1
            if tests[strat_name]["significant_10pct"]:
                count_10 += 1
    sig_count_5pct[strat_name] = count_5
    sig_count_10pct[strat_name] = count_10
    print(f"\n  {strat_name}:")
    print(f"    Significant at 5% in {count_5}/{len(OOS_PERIODS)} periods")
    print(f"    Significant at 10% in {count_10}/{len(OOS_PERIODS)} periods")


# ==================================================================
# 8. MDD COMPARISON
# ==================================================================
print("\n\n" + "=" * 80)
print("[8] MAX DRAWDOWN COMPARISON")
print("=" * 80)

mdd_comparison = {}
for strat_name, w_spy, w_gld in STRATEGIES:
    mdds = []
    for oos_name in oos_results:
        mdd = oos_results[oos_name]["strategies"][strat_name]["max_dd_pct"]
        mdds.append(mdd)

    mdd_comparison[strat_name] = {
        "avg_mdd": round(float(np.mean(mdds)), 1),
        "worst_mdd": round(float(min(mdds)), 1),
        "per_period": [round(m, 1) for m in mdds]
    }
    print(f"  {strat_name}: avg MDD={np.mean(mdds):.1f}%, worst={min(mdds):.1f}%")


# ==================================================================
# 9. FINAL VERDICT
# ==================================================================
print("\n\n" + "=" * 80)
print("[9] FINAL VERDICT")
print("=" * 80)

# Determine winner
best_avg_sharpe_strat = max(
    [(s, np.mean(all_strategy_oos_sharpes[s])) for s, _, _ in STRATEGIES],
    key=lambda x: x[1]
)

best_minimax_strat = max(
    [(s, min(all_strategy_oos_sharpes[s])) for s, _, _ in STRATEGIES],
    key=lambda x: x[1]
)

# Is 80/20 robustly better than 50/50?
strat_8020 = "80/20 SPY/GLD + 12/VIX"
r8020 = robustness_summary.get(strat_8020, {})
wins_8020 = r8020.get("wins_vs_5050", 0)
is_8020_robust = r8020.get("is_robust_4of5", False)

verdict = []
if is_8020_robust:
    verdict.append(f"80/20 ROBUSTLY beats 50/50: wins {wins_8020}/5 OOS periods")
else:
    verdict.append(f"80/20 does NOT robustly beat 50/50: wins only {wins_8020}/5 OOS periods")

verdict.append(f"Best avg Sharpe: {best_avg_sharpe_strat[0]} ({best_avg_sharpe_strat[1]:.3f})")
verdict.append(f"Best minimax: {best_minimax_strat[0]} (worst Sharpe = {min(all_strategy_oos_sharpes[best_minimax_strat[0]]):.3f})")
verdict.append(f"Full-sample 80/20 vs 50/50 bootstrap p={full_sample_test['p_value']:.3f}")

for v in verdict:
    print(f"  {v}")


# ==================================================================
# 10. SAVE RESULTS
# ==================================================================
print("\n\n[10] Saving results...")

results = {
    "experiment_id": "K646",
    "title": "Cross-OOS Validation: 80/20 vs 50/50 SPY/GLD with 12/VIX Overlay",
    "data_source": "yfinance",
    "data_period": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    "n_trading_days": int(len(ret)),
    "attribution": "[提出: Claude, 執行: Claude]",
    "references": [
        "Baur & Lucey (2010), Is Gold a Hedge or a Safe Haven?, JBF",
        "Baur & McDermott (2010), Is gold a safe haven? International evidence, JBF",
        "Erb & Harvey (2013), The Golden Dilemma, FAJ",
        "Harvey et al. (2016), ...and the Cross-Section of Expected Returns, RFS",
        "K645: GLD role analysis (optimal 20% GLD with 12/VIX, full sample)"
    ],
    "config": {
        "rf_annual": RF_ANNUAL,
        "vix_target": VIX_TARGET,
        "tx_cost_bps": TX_COST_BPS,
        "n_bootstrap": N_BOOTSTRAP,
        "strategies": [{"name": s[0], "w_spy": s[1], "w_gld": s[2]} for s in STRATEGIES],
        "oos_periods": [{"name": o[0], "start": o[1], "end": o[2]} for o in OOS_PERIODS]
    },
    "oos_results": oos_results,
    "robustness_summary": robustness_summary,
    "benchmark": {
        "strategy": benchmark,
        "avg_sharpe": round(float(np.mean(benchmark_sharpes)), 3),
        "worst_sharpe": round(float(min(benchmark_sharpes)), 3),
        "best_sharpe": round(float(max(benchmark_sharpes)), 3),
        "per_period_sharpes": [round(s, 3) for s in benchmark_sharpes]
    },
    "minimax_analysis": minimax,
    "best_minimax": {
        "strategy": best_minimax[0],
        "worst_sharpe": best_minimax[1]["worst_sharpe"]
    },
    "regime_analysis": regime_analysis,
    "regime_sharpe_summary": regime_sharpe_summary,
    "full_sample_test_8020_vs_5050": full_sample_test,
    "significance_counts_vs_5050": {
        s: {"sig_5pct": sig_count_5pct[s], "sig_10pct": sig_count_10pct[s]}
        for s in sig_count_5pct
    },
    "mdd_comparison": mdd_comparison,
    "verdict": verdict,
    "conclusion": "",  # Will be filled below
    "limitations": [
        "GLD data starts Nov 2004; earliest OOS is Jan 2008",
        "OOS periods are non-overlapping but do not cover 2006-2007 or 2025-2026",
        "12/VIX uses same-day VIX (known in real-time, no look-ahead bias)",
        "TX cost assumes 2bp per trade (conservative for retail)",
        "Bootstrap assumes iid returns within each OOS period (ignores autocorrelation)",
        "5 OOS periods may be insufficient to draw definitive conclusions",
        "Gold's exceptional performance in 2008-2012 and 2024-2025 may skew GFC/tariff periods"
    ]
}

# Build conclusion
conclusion_parts = []
if is_8020_robust:
    conclusion_parts.append(
        f"80/20 SPY/GLD + 12/VIX robustly outperforms 50/50 ({wins_8020}/5 OOS periods). "
        f"K645's finding is confirmed across diverse market conditions."
    )
else:
    conclusion_parts.append(
        f"80/20 SPY/GLD + 12/VIX does NOT robustly outperform 50/50 "
        f"(wins only {wins_8020}/5 OOS periods). K645's finding appears period-specific."
    )

conclusion_parts.append(
    f"Best average Sharpe: {best_avg_sharpe_strat[0]} "
    f"(avg={best_avg_sharpe_strat[1]:.3f})."
)
conclusion_parts.append(
    f"Best minimax (worst-case protection): {best_minimax_strat[0]} "
    f"(worst Sharpe={min(all_strategy_oos_sharpes[best_minimax_strat[0]]):.3f})."
)
conclusion_parts.append(
    f"Full-sample bootstrap p={full_sample_test['p_value']:.3f} "
    f"({'significant' if full_sample_test['significant_5pct'] else 'not significant'} at 5%)."
)

results["conclusion"] = " ".join(conclusion_parts)

# Save
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
output_path = os.path.join(script_dir, "k646_results.json")

with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\n  Results saved to: {output_path}")
print(f"\n  CONCLUSION: {results['conclusion']}")

print("\n" + "=" * 80)
print("K646 COMPLETE")
print("=" * 80)
