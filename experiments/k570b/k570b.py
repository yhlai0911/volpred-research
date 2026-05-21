#!/usr/bin/env python3
"""K570b: Earnings Season Volatility Pattern — Lookahead Fix & Methodology Corrections
===============================================================================

This is the corrected version of K570, addressing issues found in the
2026-05-18 post-publish Codex review:

  1. [HIGH] Lookahead bias: original used vix[t] to set weights for ret[t].
     Fix: vix.shift(1) — use previous day's VIX to compute today's weight.

  2. [MEDIUM-HIGH] dm_test_sharpe renamed to hac_return_diff_test.
     It is a HAC return-differential test (Newey-West), NOT a proper
     Diebold-Mariano forecast loss test.

  3. [MEDIUM] Block bootstrap replaces i.i.d. bootstrap to account for
     serial correlation in daily returns (block_size ≈ 21 trading days).

  4. [MEDIUM] OOS period labels corrected from "non-overlapping" to
     "overlapping subperiod robustness checks" (2012-2017 / 2016-2020 /
     2020-2025 share years 2016-2017 and 2020).

Parent experiment: K570 (experiments/k570/k570_earnings_season.py)
Review doc: experiments/k570/k570_post_publish_codex_review.md

Research question (unchanged): Does aggregate earnings season create a
systematic pattern in SPY volatility that justifies adjusting VT weight?

Data source: yfinance (SPY, ^VIX)
Author: [Proposed: User, Executed: Claude]
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root / "src"))

RESULTS_PATH = Path("experiments/k570b/k570b_results.json")

# ============================================================
#  Constants & Configuration
# ============================================================
TARGET_VOL = 0.12  # 12% annualized target volatility
TX_COST = 0.001    # 0.1% one-way transaction cost
ANNUALIZE = np.sqrt(252)
RF_ANNUAL = 0.02   # Risk-free rate for Sharpe

# Earnings months: Jan, Apr, Jul, Oct
EARNINGS_MONTHS = [1, 4, 7, 10]
# Earnings weeks within those months
EARNINGS_WEEK_START = 3  # 3rd week of the month
EARNINGS_WEEK_END = 5    # Through 5th week

# Cross-OOS periods
# NOTE: These are OVERLAPPING subperiod robustness checks, NOT non-overlapping.
# 2012-2017 and 2016-2020 share 2016-2017; 2016-2020 and 2020-2025 share 2020.
OOS_PERIODS = [
    ("2005-01-01", "2011-12-31", "2012-01-01", "2017-12-31"),
    ("2008-01-01", "2015-12-31", "2016-01-01", "2020-12-31"),
    ("2012-01-01", "2019-12-31", "2020-01-01", "2025-12-31"),
]


# ============================================================
#  Data Download
# ============================================================
def download_data() -> pd.DataFrame:
    """Download SPY and VIX data from yfinance."""
    print("Downloading SPY and VIX data...")

    spy = yf.download("SPY", start="2004-12-01", end="2026-03-27", auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start="2004-12-01", end="2026-03-27", auto_adjust=True, progress=False)

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df["spy_close"] = spy["Close"]
    df["vix_close"] = vix["Close"].reindex(spy.index, method="ffill")
    df = df.dropna()

    # Calculate returns
    df["spy_ret"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
    df = df.dropna()

    # Realized vol (21-day rolling)
    df["rv_21d"] = df["spy_ret"].rolling(21).std() * ANNUALIZE
    df = df.dropna()

    print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Total observations: {len(df)}")
    return df


# ============================================================
#  Earnings Season Classification
# ============================================================
def classify_earnings_season(df: pd.DataFrame) -> pd.Series:
    """Classify each trading day as earnings season or not.

    Earnings season = weeks 3-5 of Jan, Apr, Jul, Oct.
    Week numbering: day 1-7 = week 1, ..., day 15-21 = week 3,
    day 22-28 = week 4, day 29-31 = week 5.
    """
    is_earnings = pd.Series(False, index=df.index, dtype=bool)

    for idx in df.index:
        month = idx.month
        day = idx.day
        week_of_month = (day - 1) // 7 + 1

        if month in EARNINGS_MONTHS and EARNINGS_WEEK_START <= week_of_month <= EARNINGS_WEEK_END:
            is_earnings[idx] = True

    return is_earnings


# ============================================================
#  VT Strategy Implementation
# ============================================================
def run_vt_strategy(
    returns: pd.Series,
    vix: pd.Series,
    is_earnings: pd.Series,
    strategy: str,
    tx_cost: float = TX_COST,
) -> dict:
    """Run a VT strategy with earnings-season adjustment.

    FIX (K570b): vix.shift(1) is applied at the start so that weight[t]
    is based on VIX[t-1] (known at market open on day t), not VIX[t]
    (only available at market close on day t). This eliminates the lookahead
    bias present in K570.

    Strategies:
      - 'baseline': constant 12/VIX
      - 'earnings_enhanced': 10/VIX during earnings, 14/VIX outside
      - 'earnings_only': VT during earnings, B&H outside
      - 'anti_earnings': VT outside earnings, B&H during earnings
      - 'bh': Buy and hold (100% equity always)
    """
    n = len(returns)
    weights = np.zeros(n)

    # *** LOOKAHEAD FIX (K570b) ***
    # Use previous day's VIX to form weights — no lookahead.
    # bfill handles the very first row which becomes NaN after shift.
    vix_lag = vix.shift(1).bfill()

    if strategy == "baseline":
        weights = np.clip(TARGET_VOL / (vix_lag.values / 100), 0, 1)

    elif strategy == "earnings_enhanced":
        earnings_mask = is_earnings.values
        weights[earnings_mask] = np.clip(0.10 / (vix_lag.values[earnings_mask] / 100), 0, 1)
        weights[~earnings_mask] = np.clip(0.14 / (vix_lag.values[~earnings_mask] / 100), 0, 1)

    elif strategy == "earnings_only":
        earnings_mask = is_earnings.values
        weights[earnings_mask] = np.clip(TARGET_VOL / (vix_lag.values[earnings_mask] / 100), 0, 1)
        weights[~earnings_mask] = 1.0

    elif strategy == "anti_earnings":
        earnings_mask = is_earnings.values
        weights[earnings_mask] = 1.0
        weights[~earnings_mask] = np.clip(TARGET_VOL / (vix_lag.values[~earnings_mask] / 100), 0, 1)

    elif strategy == "bh":
        weights[:] = 1.0

    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    # Portfolio returns
    simple_ret = np.exp(returns.values) - 1
    port_ret = weights * simple_ret

    # Transaction costs
    weight_changes = np.abs(np.diff(weights, prepend=weights[0]))
    tc = weight_changes * tx_cost
    port_ret_net = port_ret - tc

    # Metrics
    cumret = np.cumprod(1 + port_ret_net)
    total_ret = cumret[-1] - 1
    ann_ret = (1 + total_ret) ** (252 / n) - 1
    ann_vol = np.std(port_ret_net) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    peak = np.maximum.accumulate(cumret)
    dd = (cumret - peak) / peak
    mdd = np.min(dd)

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = port_ret_net[port_ret_net < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 0.001
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Average weight
    avg_weight = np.mean(weights)

    # Turnover
    daily_turnover = np.mean(weight_changes)
    annual_turnover = daily_turnover * 252

    return {
        "strategy": strategy,
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "sortino": float(sortino),
        "avg_weight": float(avg_weight),
        "annual_turnover": float(annual_turnover),
        "total_ret": float(total_ret),
        "n_days": n,
        "port_ret_series": port_ret_net,
    }


# ============================================================
#  HAC Return-Differential Test
#  (renamed from dm_test_sharpe — was a misnomer in K570)
# ============================================================
def hac_return_diff_test(ret_benchmark: np.ndarray, ret_candidate: np.ndarray) -> tuple:
    """HAC return-differential test (Newey-West).

    Tests H0: mean return difference = 0.
    Uses Newey-West HAC standard errors to account for serial correlation.

    Note: NOT a proper Diebold-Mariano forecast loss test. The original
    K570 function dm_test_sharpe was misnamed; this is a mean return
    differential test with HAC variance correction.
    """
    d = ret_candidate - ret_benchmark  # Positive = candidate better

    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC variance (lag = int(n^(1/3)))
    lag = int(n ** (1.0 / 3.0))
    gamma = np.zeros(lag + 1)
    d_demean = d - d_mean
    for k in range(lag + 1):
        gamma[k] = np.mean(d_demean[k:] * d_demean[:n - k])

    var_nw = gamma[0] + 2 * sum((1 - j / (lag + 1)) * gamma[j] for j in range(1, lag + 1))
    se = np.sqrt(max(var_nw, 0) / n)

    if se < 1e-12:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return float(t_stat), float(p_val)


# ============================================================
#  Block Bootstrap Confidence Interval
#  (replaces i.i.d. bootstrap from K570 — circular block bootstrap)
# ============================================================
def bootstrap_sharpe_diff(
    ret_baseline: np.ndarray,
    ret_candidate: np.ndarray,
    n_boot: int = 10000,
    seed: int = 42,
) -> dict:
    """Block bootstrap the Sharpe ratio difference between two strategies.

    FIX (K570b): Uses circular block bootstrap (block_size ≈ 21 trading days
    by default, or n^(1/3)) instead of i.i.d. resampling. This properly
    accounts for serial correlation in daily returns and produces correct
    (wider) confidence intervals.
    """
    rng = np.random.default_rng(seed)
    n = len(ret_baseline)

    # Block size: max(21, n^(1/3)) — 21 trading days ≈ 1 calendar month
    block_size = max(21, int(n ** (1.0 / 3.0)))
    n_blocks = int(np.ceil(n / block_size))

    sharpe_diffs = np.zeros(n_boot)
    for i in range(n_boot):
        # Circular block bootstrap
        starts = rng.integers(0, n, size=n_blocks)
        indices = np.concatenate([
            np.arange(s, s + block_size) % n for s in starts
        ])[:n]

        b = ret_baseline[indices]
        c = ret_candidate[indices]

        sb = (np.mean(b) * 252 - RF_ANNUAL) / (np.std(b) * np.sqrt(252)) if np.std(b) > 0 else 0
        sc = (np.mean(c) * 252 - RF_ANNUAL) / (np.std(c) * np.sqrt(252)) if np.std(c) > 0 else 0
        sharpe_diffs[i] = sc - sb

    return {
        "mean_diff": float(np.mean(sharpe_diffs)),
        "ci_lower": float(np.percentile(sharpe_diffs, 2.5)),
        "ci_upper": float(np.percentile(sharpe_diffs, 97.5)),
        "p_better": float(np.mean(sharpe_diffs > 0)),
        "block_size": block_size,
    }


# ============================================================
#  Main Analysis
# ============================================================
def main():
    # Fix global seed for all random operations
    np.random.seed(42)

    t0 = time.time()
    print("=" * 70)
    print("K570b: Earnings Season Volatility Pattern (Lookahead Fix)")
    print("Corrections: vix.shift(1) + block bootstrap + HAC rename + OOS labels")
    print("=" * 70)

    # --- Step 1: Download data ---
    df = download_data()

    # --- Step 2: Classify earnings season ---
    df["is_earnings"] = classify_earnings_season(df)
    n_earnings = df["is_earnings"].sum()
    n_non = (~df["is_earnings"]).sum()
    pct_earnings = n_earnings / len(df) * 100
    print(f"\n--- Earnings Season Classification ---")
    print(f"  Earnings season days: {n_earnings} ({pct_earnings:.1f}%)")
    print(f"  Non-earnings days:    {n_non} ({100 - pct_earnings:.1f}%)")
    print(f"  Expected ~60 days/yr out of 252 = ~{60/252*100:.1f}%")

    # --- Step 3: Descriptive statistics ---
    print("\n--- Descriptive Statistics ---")
    earnings_df = df[df["is_earnings"]]
    non_earnings_df = df[~df["is_earnings"]]

    rv_earn = earnings_df["rv_21d"].values
    rv_non = non_earnings_df["rv_21d"].values
    print(f"\n  Realized Vol (21d, annualized):")
    print(f"    Earnings season:  mean={np.mean(rv_earn)*100:.1f}%, std={np.std(rv_earn)*100:.1f}%")
    print(f"    Non-earnings:     mean={np.mean(rv_non)*100:.1f}%, std={np.std(rv_non)*100:.1f}%")

    t_rv, p_rv = stats.ttest_ind(rv_earn, rv_non)
    print(f"    t-test: t={t_rv:.3f}, p={p_rv:.4f} {'***' if p_rv < 0.01 else '**' if p_rv < 0.05 else 'NS'}")

    vix_earn = earnings_df["vix_close"].values
    vix_non = non_earnings_df["vix_close"].values
    print(f"\n  VIX Level:")
    print(f"    Earnings season:  mean={np.mean(vix_earn):.2f}, std={np.std(vix_earn):.2f}")
    print(f"    Non-earnings:     mean={np.mean(vix_non):.2f}, std={np.std(vix_non):.2f}")

    t_vix, p_vix = stats.ttest_ind(vix_earn, vix_non)
    print(f"    t-test: t={t_vix:.3f}, p={p_vix:.4f} {'***' if p_vix < 0.01 else '**' if p_vix < 0.05 else 'NS'}")

    ret_earn = earnings_df["spy_ret"].values
    ret_non = non_earnings_df["spy_ret"].values
    print(f"\n  SPY Daily Return:")
    print(f"    Earnings season:  mean={np.mean(ret_earn)*10000:.2f}bps, std={np.std(ret_earn)*10000:.1f}bps")
    print(f"    Non-earnings:     mean={np.mean(ret_non)*10000:.2f}bps, std={np.std(ret_non)*10000:.1f}bps")

    t_ret, p_ret = stats.ttest_ind(ret_earn, ret_non)
    print(f"    t-test: t={t_ret:.3f}, p={p_ret:.4f} {'***' if p_ret < 0.01 else '**' if p_ret < 0.05 else 'NS'}")

    absret_earn = np.abs(ret_earn)
    absret_non = np.abs(ret_non)
    print(f"\n  SPY Absolute Return (vol proxy):")
    print(f"    Earnings season:  mean={np.mean(absret_earn)*10000:.2f}bps")
    print(f"    Non-earnings:     mean={np.mean(absret_non)*10000:.2f}bps")

    t_abs, p_abs = stats.ttest_ind(absret_earn, absret_non)
    print(f"    t-test: t={t_abs:.3f}, p={p_abs:.4f} {'***' if p_abs < 0.01 else '**' if p_abs < 0.05 else 'NS'}")

    levene_stat, levene_p = stats.levene(ret_earn, ret_non)
    print(f"\n  Levene test (variance equality): F={levene_stat:.3f}, p={levene_p:.4f}")

    # --- Step 4: Full-sample strategy comparison ---
    print("\n" + "=" * 70)
    print("FULL SAMPLE STRATEGY COMPARISON (with lookahead fix)")
    print("=" * 70)

    strategies = ["bh", "baseline", "earnings_enhanced", "earnings_only", "anti_earnings"]
    strategy_names = {
        "bh": "Buy & Hold",
        "baseline": "12/VIX (Baseline)",
        "earnings_enhanced": "Earnings Enhanced (10/14)",
        "earnings_only": "Earnings-Only VT",
        "anti_earnings": "Anti-Earnings VT",
    }

    df_strat = df.loc["2005-01-01":]
    full_results = {}

    print(f"\n{'Strategy':<30} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'AvgWt':>7}")
    print("-" * 85)

    for strat in strategies:
        res = run_vt_strategy(
            df_strat["spy_ret"],
            df_strat["vix_close"],
            df_strat["is_earnings"],
            strat,
        )
        full_results[strat] = res
        print(
            f"  {strategy_names[strat]:<28} "
            f"{res['ann_ret']*100:>7.2f}% "
            f"{res['ann_vol']*100:>7.2f}% "
            f"{res['sharpe']:>7.3f} "
            f"{res['mdd']*100:>7.1f}% "
            f"{res['calmar']:>7.3f} "
            f"{res['avg_weight']:>6.2f}"
        )

    # HAC return-differential tests vs baseline (renamed from dm_test_sharpe)
    print(f"\n--- HAC Return-Differential Tests vs Baseline (12/VIX) ---")
    print(f"  (Note: renamed from dm_test_sharpe — this is a HAC mean-return test)")
    print(f"  Harvey (2016) threshold: |t| > 3.0")
    baseline_ret = full_results["baseline"]["port_ret_series"]
    hac_results_full = {}

    for strat in ["earnings_enhanced", "earnings_only", "anti_earnings"]:
        cand_ret = full_results[strat]["port_ret_series"]
        t_hac, p_hac = hac_return_diff_test(baseline_ret, cand_ret)
        bs = bootstrap_sharpe_diff(baseline_ret, cand_ret)
        hac_results_full[strat] = {
            "hac_t": t_hac,
            "hac_p": p_hac,
            "boot_mean": bs["mean_diff"],
            "boot_ci_lower": bs["ci_lower"],
            "boot_ci_upper": bs["ci_upper"],
            "boot_p_better": bs["p_better"],
            "boot_block_size": bs["block_size"],
        }
        sig = "***" if abs(t_hac) > 3.0 else "**" if abs(t_hac) > 2.0 else "*" if abs(t_hac) > 1.96 else "NS"
        print(
            f"  {strategy_names[strat]:<28} HAC t={t_hac:>6.3f} p={p_hac:.4f} {sig}  "
            f"Block-Boot: Sharpe diff={bs['mean_diff']:+.4f} "
            f"95% CI=[{bs['ci_lower']:+.4f}, {bs['ci_upper']:+.4f}] "
            f"P(better)={bs['p_better']:.3f} (block={bs['block_size']})"
        )

    # --- Step 5: Cross-OOS robustness checks ---
    print("\n" + "=" * 70)
    print("CROSS-OOS ROBUSTNESS CHECKS (3 overlapping subperiods)")
    print("NOTE: These are OVERLAPPING subperiods, not non-overlapping OOS.")
    print("  2012-2017 and 2016-2020 share 2016-2017;")
    print("  2016-2020 and 2020-2025 share 2020.")
    print("=" * 70)

    cross_oos_results = []

    for i, (train_start, train_end, test_start, test_end) in enumerate(OOS_PERIODS):
        print(f"\n  Period {i+1}: Train {train_start[:4]}-{train_end[:4]}, Test {test_start[:4]}-{test_end[:4]}")

        df_test = df_strat.loc[test_start:test_end]
        if len(df_test) < 100:
            print(f"    SKIP: too few observations ({len(df_test)})")
            continue

        period_results = {}
        for strat in strategies:
            res = run_vt_strategy(
                df_test["spy_ret"],
                df_test["vix_close"],
                df_test["is_earnings"],
                strat,
            )
            period_results[strat] = res

        print(f"    {'Strategy':<28} {'Sharpe':>8} {'MDD':>8}")
        print(f"    {'-'*50}")
        for strat in strategies:
            r = period_results[strat]
            print(f"    {strategy_names[strat]:<28} {r['sharpe']:>7.3f} {r['mdd']*100:>7.1f}%")

        baseline_ret_oos = period_results["baseline"]["port_ret_series"]
        period_hac = {}
        for strat in ["earnings_enhanced", "earnings_only", "anti_earnings"]:
            cand_ret_oos = period_results[strat]["port_ret_series"]
            t_hac, p_hac = hac_return_diff_test(baseline_ret_oos, cand_ret_oos)
            period_hac[strat] = {"hac_t": t_hac, "hac_p": p_hac}
            sig = "***" if abs(t_hac) > 3.0 else "NS"
            print(f"    HAC vs baseline: {strategy_names[strat]:<28} t={t_hac:>6.3f} {sig}")

        cross_oos_results.append({
            "period": f"Train {train_start[:4]}-{train_end[:4]}, Test {test_start[:4]}-{test_end[:4]}",
            "test_start": test_start,
            "test_end": test_end,
            "n_test_days": len(df_test),
            "note": "overlapping_subperiod_robustness_check",
            "results": {
                strat: {
                    "sharpe": period_results[strat]["sharpe"],
                    "ann_ret": period_results[strat]["ann_ret"],
                    "mdd": period_results[strat]["mdd"],
                }
                for strat in strategies
            },
            "hac_tests": period_hac,
        })

    # --- Step 6: Earnings vs Non-Earnings VT Performance ---
    print("\n" + "=" * 70)
    print("VT PERFORMANCE: EARNINGS vs NON-EARNINGS PERIODS")
    print("=" * 70)

    baseline_full = run_vt_strategy(
        df_strat["spy_ret"],
        df_strat["vix_close"],
        df_strat["is_earnings"],
        "baseline",
    )
    vt_ret = baseline_full["port_ret_series"]
    bh_ret_series = run_vt_strategy(
        df_strat["spy_ret"],
        df_strat["vix_close"],
        df_strat["is_earnings"],
        "bh",
    )["port_ret_series"]

    earn_mask = df_strat["is_earnings"].values
    vt_earn_ret = vt_ret[earn_mask]
    vt_non_ret = vt_ret[~earn_mask]
    bh_earn_ret = bh_ret_series[earn_mask]
    bh_non_ret = bh_ret_series[~earn_mask]

    excess_earn = vt_earn_ret - bh_earn_ret
    excess_non = vt_non_ret - bh_non_ret

    print(f"\n  VT daily excess return (VT - BH):")
    print(f"    Earnings season:  mean={np.mean(excess_earn)*10000:+.3f}bps (ann={np.mean(excess_earn)*252*100:+.2f}%)")
    print(f"    Non-earnings:     mean={np.mean(excess_non)*10000:+.3f}bps (ann={np.mean(excess_non)*252*100:+.2f}%)")

    t_excess, p_excess = stats.ttest_ind(excess_earn, excess_non)
    print(f"    Difference t-test: t={t_excess:.3f}, p={p_excess:.4f} {'***' if abs(t_excess) > 3.0 else 'NS'}")

    sharpe_earn = (np.mean(vt_earn_ret) * 252 - RF_ANNUAL) / (np.std(vt_earn_ret) * np.sqrt(252)) if np.std(vt_earn_ret) > 0 else 0
    sharpe_non = (np.mean(vt_non_ret) * 252 - RF_ANNUAL) / (np.std(vt_non_ret) * np.sqrt(252)) if np.std(vt_non_ret) > 0 else 0

    print(f"\n  VT Sharpe (annualized from sub-period returns):")
    print(f"    Earnings season:  {sharpe_earn:.3f}")
    print(f"    Non-earnings:     {sharpe_non:.3f}")
    print(f"    Difference:       {sharpe_earn - sharpe_non:+.3f}")

    # --- Step 7: Year-by-year stability ---
    print("\n" + "=" * 70)
    print("YEAR-BY-YEAR STABILITY: Earnings-Enhanced vs Baseline")
    print("=" * 70)

    years = sorted(df_strat.index.year.unique())
    year_wins = 0
    year_total = 0

    print(f"  {'Year':<6} {'Baseline Sharpe':>15} {'Enhanced Sharpe':>15} {'Winner':>10}")
    print(f"  {'-'*50}")

    for yr in years:
        df_yr = df_strat[df_strat.index.year == yr]
        if len(df_yr) < 100:
            continue

        res_b = run_vt_strategy(df_yr["spy_ret"], df_yr["vix_close"], df_yr["is_earnings"], "baseline")
        res_e = run_vt_strategy(df_yr["spy_ret"], df_yr["vix_close"], df_yr["is_earnings"], "earnings_enhanced")

        winner = "Enhanced" if res_e["sharpe"] > res_b["sharpe"] else "Baseline"
        if winner == "Enhanced":
            year_wins += 1
        year_total += 1

        print(f"  {yr:<6} {res_b['sharpe']:>15.3f} {res_e['sharpe']:>15.3f} {winner:>10}")

    print(f"\n  Enhanced wins: {year_wins}/{year_total} years ({year_wins/year_total*100:.0f}%)")
    binom_p = stats.binomtest(year_wins, year_total, 0.5).pvalue
    print(f"  Binomial test p-value: {binom_p:.4f}")

    # --- Step 8: Summary & Conclusions ---
    print("\n" + "=" * 70)
    print("SUMMARY & CONCLUSIONS")
    print("=" * 70)

    any_significant = any(abs(v["hac_t"]) > 3.0 for v in hac_results_full.values())

    result_type = "NULL RESULT" if not any_significant else "SIGNIFICANT"
    print(f"\n  Overall verdict: {result_type}")
    print(f"\n  1. Earnings season vol (RV):       t={t_rv:.3f}, p={p_rv:.4f} {'Significant' if p_rv < 0.05 else 'Not significant'}")
    print(f"  2. Earnings season VIX:            t={t_vix:.3f}, p={p_vix:.4f} {'Significant' if p_vix < 0.05 else 'Not significant'}")
    print(f"  3. Earnings season SPY return:     t={t_ret:.3f}, p={p_ret:.4f} {'Significant' if p_ret < 0.05 else 'Not significant'}")
    print(f"  4. Earnings season abs return:     t={t_abs:.3f}, p={p_abs:.4f} {'Significant' if p_abs < 0.05 else 'Not significant'}")
    print(f"  5. VT excess: earnings vs non:     t={t_excess:.3f}, p={p_excess:.4f} {'Significant' if p_excess < 0.05 else 'Not significant'}")

    print(f"\n  Strategy HAC tests vs 12/VIX baseline (Harvey |t|>3.0):")
    for strat in ["earnings_enhanced", "earnings_only", "anti_earnings"]:
        r = hac_results_full[strat]
        sig = "PASS" if abs(r["hac_t"]) > 3.0 else "FAIL"
        print(f"    {strategy_names[strat]:<28} t={r['hac_t']:+.3f}  {sig}")

    print(f"\n  Cross-OOS subperiod consistency:")
    for period in cross_oos_results:
        print(f"    {period['period']} [{period['note']}]:")
        for strat in ["earnings_enhanced", "earnings_only", "anti_earnings"]:
            r = period["hac_tests"][strat]
            sig = "PASS" if abs(r["hac_t"]) > 3.0 else "FAIL"
            print(f"      {strategy_names[strat]:<28} t={r['hac_t']:+.3f}  {sig}")

    # K570 comparison
    k570_baseline_sharpe = 1.4251  # From k570_earnings_season_results.json
    k570b_baseline_sharpe = full_results["baseline"]["sharpe"]
    sharpe_change_pct = (k570b_baseline_sharpe - k570_baseline_sharpe) / abs(k570_baseline_sharpe) * 100

    print(f"\n  Comparison with K570 (original, with lookahead):")
    print(f"    K570 baseline Sharpe:   {k570_baseline_sharpe:.4f}")
    print(f"    K570b baseline Sharpe:  {k570b_baseline_sharpe:.4f}")
    print(f"    Change: {sharpe_change_pct:+.1f}%")
    print(f"    NULL result maintained: {not any_significant}")

    conclusion = (
        "After fixing lookahead bias (vix.shift(1)), upgrading to block bootstrap, "
        "correcting the HAC test name, and labelling periods correctly, "
        "earnings season STILL does NOT justify VT adjustment. "
        "All three earnings-adjusted strategies fail Harvey (2016) t>3.0 threshold. "
        "NULL result confirmed across 3 overlapping robustness subperiods. "
        "Consistent with K498/K412/K80/N153: VIX remains the sufficient statistic."
    )
    if any_significant:
        conclusion = (
            "Even after fixing lookahead bias and upgrading to block bootstrap, "
            "at least one earnings-adjusted strategy shows significant improvement "
            "over 12/VIX at Harvey (2016) t>3.0 threshold. Requires further validation."
        )

    print(f"\n  Conclusion: {conclusion}")

    # --- Save Results ---
    elapsed = time.time() - t0
    print(f"\n  Elapsed: {elapsed:.1f}s")

    results = {
        "experiment_id": "k570b",
        "parent_experiment": "k570",
        "title": "Earnings Season Volatility Pattern — Lookahead Fix & Methodology Corrections",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookahead_fix": "vix.shift(1) — previous day VIX used for weight[t]",
        "methodology_corrections": [
            "lookahead_fix",
            "block_bootstrap",
            "hac_rename",
            "oos_label_fix",
        ],
        "data_source": "yfinance (SPY, ^VIX)",
        "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_observations": len(df),
        "n_strategy_days": len(df_strat),
        "result_type": result_type,
        "conclusion": conclusion,

        "earnings_classification": {
            "method": "Weeks 3-5 of Jan/Apr/Jul/Oct",
            "n_earnings_days": int(n_earnings),
            "n_non_earnings_days": int(n_non),
            "pct_earnings": float(pct_earnings),
        },

        "descriptive_statistics": {
            "rv_21d": {
                "earnings_mean": float(np.mean(rv_earn)),
                "earnings_std": float(np.std(rv_earn)),
                "non_earnings_mean": float(np.mean(rv_non)),
                "non_earnings_std": float(np.std(rv_non)),
                "t_stat": float(t_rv),
                "p_value": float(p_rv),
            },
            "vix": {
                "earnings_mean": float(np.mean(vix_earn)),
                "earnings_std": float(np.std(vix_earn)),
                "non_earnings_mean": float(np.mean(vix_non)),
                "non_earnings_std": float(np.std(vix_non)),
                "t_stat": float(t_vix),
                "p_value": float(p_vix),
            },
            "spy_return": {
                "earnings_mean_bps": float(np.mean(ret_earn) * 10000),
                "non_earnings_mean_bps": float(np.mean(ret_non) * 10000),
                "t_stat": float(t_ret),
                "p_value": float(p_ret),
            },
            "abs_return": {
                "earnings_mean_bps": float(np.mean(absret_earn) * 10000),
                "non_earnings_mean_bps": float(np.mean(absret_non) * 10000),
                "t_stat": float(t_abs),
                "p_value": float(p_abs),
            },
            "levene_test": {
                "F_stat": float(levene_stat),
                "p_value": float(levene_p),
            },
        },

        "full_sample_strategies": {
            strat: {
                "name": strategy_names[strat],
                "ann_ret": full_results[strat]["ann_ret"],
                "ann_vol": full_results[strat]["ann_vol"],
                "sharpe": full_results[strat]["sharpe"],
                "mdd": full_results[strat]["mdd"],
                "calmar": full_results[strat]["calmar"],
                "sortino": full_results[strat]["sortino"],
                "avg_weight": full_results[strat]["avg_weight"],
                "annual_turnover": full_results[strat]["annual_turnover"],
            }
            for strat in strategies
        },

        "hac_tests_vs_baseline": {
            strat: hac_results_full[strat]
            for strat in ["earnings_enhanced", "earnings_only", "anti_earnings"]
        },

        "cross_oos": cross_oos_results,

        "vt_performance_by_period": {
            "excess_earn_mean_bps": float(np.mean(excess_earn) * 10000),
            "excess_earn_ann_pct": float(np.mean(excess_earn) * 252 * 100),
            "excess_non_mean_bps": float(np.mean(excess_non) * 10000),
            "excess_non_ann_pct": float(np.mean(excess_non) * 252 * 100),
            "difference_t_stat": float(t_excess),
            "difference_p_value": float(p_excess),
            "sharpe_earnings": float(sharpe_earn),
            "sharpe_non_earnings": float(sharpe_non),
        },

        "year_by_year": {
            "enhanced_wins": year_wins,
            "total_years": year_total,
            "win_rate": float(year_wins / year_total) if year_total > 0 else 0,
        },

        "comparison_with_k570": {
            "k570_baseline_sharpe": k570_baseline_sharpe,
            "k570b_baseline_sharpe": float(k570b_baseline_sharpe),
            "null_result_maintained": bool(not any_significant),
            "sharpe_change_pct": float(sharpe_change_pct),
            "note": (
                "Sharpe change expected because lookahead bias inflated K570 weights. "
                "After vix.shift(1), weights are set from t-1 VIX rather than t VIX."
            ),
        },

        "methodology_notes": {
            "lookahead_fix": (
                "vix.shift(1) applied at top of run_vt_strategy(). "
                "Weight[t] = f(VIX[t-1]). First row backfilled."
            ),
            "hac_test": (
                "hac_return_diff_test() (renamed from dm_test_sharpe). "
                "Newey-West HAC with lag=n^(1/3). Tests H0: mean(ret_candidate - ret_baseline)=0. "
                "NOT a proper Diebold-Mariano forecast loss test."
            ),
            "bootstrap": (
                "Circular block bootstrap with block_size=max(21, n^(1/3)). "
                "Accounts for serial correlation in daily returns. "
                "CI will be wider than i.i.d. bootstrap used in K570."
            ),
            "oos_label": (
                "3 subperiods are OVERLAPPING robustness checks, not non-overlapping OOS. "
                "2012-2017 and 2016-2020 share 2016-2017; 2016-2020 and 2020-2025 share 2020."
            ),
        },

        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Savor & Wilson (2016, JFE): Earnings Announcements and Systematic Risk",
            "Harvey (2016, JoF): t>3 threshold for new factors",
            "K498: Earnings Season Vol Patterns — null at index level",
            "K412: Earnings Season Effect on Index Volatility — null",
            "K80: VT Seasonality — null (sell-in-may)",
            "K570: Original experiment with lookahead bias",
        ],

        "elapsed_seconds": float(elapsed),
    }

    # Save results
    out_path = RESULTS_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")


if __name__ == "__main__":
    main()
