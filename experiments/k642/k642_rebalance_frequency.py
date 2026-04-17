#!/usr/bin/env python3
"""
K642: Optimal Rebalancing Frequency for VT Strategies
======================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K634 showed fixed params beat rolling (monthly refit adds noise).
  K635 showed turnover reduction is the main benefit.
  K641 showed architecture matters more than refit frequency.
  Now systematically test: what is the optimal rebalancing frequency?

Prior Knowledge:
  - K634: Fixed params beat rolling GARCH (QLIKE 1.464 vs 1.492 for SPY)
  - K635: Turnover reduction is main benefit of fixed params
  - K641: Architecture matters more than refit frequency
  - K499: TX cost sensitivity analysis for strategies
  - 50/50 SPY/GLD with 12/VIX is our best simple strategy

References:
  - DeMiguel, Garlappi & Uppal (2009) "Optimal vs naive diversification" RFS
  - Kirby & Ostdiek (2012) "It's all in the timing: Simple active portfolio
    strategies that outperform naive diversification" JFE
  - Masters (2003) "Rebalancing" Journal of Portfolio Management
  - Tokat & Wicas (2007) "Portfolio rebalancing in theory and practice" JPM
  - Fleming, Kirby & Ostdiek (2003) "The economic value of volatility timing
    using realized volatility" JFE

Data: SPY, GLD, VIX daily via yfinance (2006-01-01 to 2026-03-27)
OOS period: 2010-01-01 to 2026-03-27 (full backtest)
Analysis type: 實證分析（真實數據）
"""

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

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

START_TIME = time.time()
EXPERIMENT_ID = "K642"
BASE_DIR = Path(__file__).resolve().parent
RELATIVE_DIR = Path("experiments") / "k642"

# ============================================================================
# Configuration
# ============================================================================
DATA_START = "2005-01-01"
DATA_END = "2026-03-28"
ANALYSIS_START = "2006-01-01"
OOS_START = "2010-01-01"
OOS_END = "2026-03-27"
TX_COST_US_BP = 2        # US: 2bp round-trip
TX_COST_TW_BP = 18.5     # Taiwan: 18.5bp round-trip
RANDOM_SEED = 42

np.random.seed(RANDOM_SEED)


def P(msg):
    """Print with flush for real-time output."""
    print(msg, flush=True)


# ============================================================================
# Data Download
# ============================================================================
def download_data(ticker: str) -> pd.DataFrame:
    P(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df["return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna()
    return df


def download_vix() -> pd.Series:
    P("  Downloading VIX...")
    vix = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix["Close"].dropna()


# ============================================================================
# Strategy: 50/50 SPY/GLD with 12/VIX allocation
# ============================================================================
def compute_target_weights(vix_level: float) -> dict:
    """
    50/50 SPY/GLD with 12/VIX allocation.
    w = min(12/VIX, 1.0)
    spy_w = 0.5 * w, gld_w = 0.5 * w, cash = 1 - w
    """
    w = min(12.0 / vix_level, 1.0) if vix_level > 0 else 1.0
    return {
        "SPY": 0.5 * w,
        "GLD": 0.5 * w,
        "CASH": max(0, 1.0 - w),
    }


# ============================================================================
# Backtest Engine with Rebalancing Frequency
# ============================================================================
def run_backtest(
    spy_ret: pd.Series,
    gld_ret: pd.Series,
    vix_series: pd.Series,
    rebalance_rule: str,
    tx_cost_bp: float,
    threshold: float = 0.0,
) -> dict:
    """
    Run backtest for 50/50 SPY/GLD with 12/VIX, with specified rebalancing rule.

    rebalance_rule: 'daily', 'weekly', 'biweekly', 'monthly', 'quarterly',
                    'semiannual', 'annual', 'threshold_5', 'threshold_10'
    tx_cost_bp: transaction cost in basis points (round-trip)
    threshold: minimum weight change to trigger rebalance (for threshold-based)
    """
    # Align all series to common dates
    common_idx = spy_ret.index.intersection(gld_ret.index).intersection(vix_series.index)
    common_idx = common_idx.sort_values()

    spy_r = spy_ret.loc[common_idx].values
    gld_r = gld_ret.loc[common_idx].values
    vix_v = vix_series.loc[common_idx].values
    dates = common_idx

    T = len(dates)
    tx_cost_frac = tx_cost_bp / 10000.0  # convert bp to fraction

    # Track portfolio
    port_returns = np.zeros(T)
    trade_flags = np.zeros(T, dtype=bool)  # True if rebalanced on this day
    tx_costs_daily = np.zeros(T)

    # Initialize: first day's target weights
    target = compute_target_weights(vix_v[0])
    current_spy_w = target["SPY"]
    current_gld_w = target["GLD"]
    current_cash_w = target["CASH"]
    trade_flags[0] = True

    # Helper: determine if it's a rebalance day
    def is_rebalance_day(i, rule, dates_arr):
        if rule == 'daily':
            return True
        elif rule == 'weekly':
            # Rebalance on Monday (weekday=0)
            return dates_arr[i].weekday() == 0
        elif rule == 'biweekly':
            # Rebalance every other Monday
            if dates_arr[i].weekday() != 0:
                return False
            # Count Mondays from start
            start_date = dates_arr[0]
            days_diff = (dates_arr[i] - start_date).days
            week_num = days_diff // 7
            return week_num % 2 == 0
        elif rule == 'monthly':
            # First trading day of month
            if i == 0:
                return True
            return dates_arr[i].month != dates_arr[i-1].month
        elif rule == 'quarterly':
            # First trading day of quarter
            if i == 0:
                return True
            curr_q = (dates_arr[i].month - 1) // 3
            prev_q = (dates_arr[i-1].month - 1) // 3
            return curr_q != prev_q or dates_arr[i].year != dates_arr[i-1].year
        elif rule == 'semiannual':
            # First trading day of half-year (Jan, Jul)
            if i == 0:
                return True
            curr_h = 0 if dates_arr[i].month <= 6 else 1
            prev_h = 0 if dates_arr[i-1].month <= 6 else 1
            return curr_h != prev_h or dates_arr[i].year != dates_arr[i-1].year
        elif rule == 'annual':
            # First trading day of year
            if i == 0:
                return True
            return dates_arr[i].year != dates_arr[i-1].year
        elif rule.startswith('threshold'):
            # Threshold-based: always check, but only trade if change > threshold
            return True  # will be filtered by threshold check below
        return False

    for i in range(1, T):
        # Daily drift of weights (before rebalancing)
        # After day i-1 returns, weights drift
        spy_growth = current_spy_w * (1.0 + spy_r[i-1])
        gld_growth = current_gld_w * (1.0 + gld_r[i-1])
        cash_growth = current_cash_w * 1.0  # cash earns 0 (simplified)
        total = spy_growth + gld_growth + cash_growth

        if total > 0:
            drifted_spy_w = spy_growth / total
            drifted_gld_w = gld_growth / total
            drifted_cash_w = cash_growth / total
        else:
            drifted_spy_w = current_spy_w
            drifted_gld_w = current_gld_w
            drifted_cash_w = current_cash_w

        # Determine new target weights
        new_target = compute_target_weights(vix_v[i])

        # Check if we should rebalance
        rebalance = False
        if is_rebalance_day(i, rebalance_rule, dates):
            if rebalance_rule.startswith('threshold'):
                # Only rebalance if weight delta exceeds threshold
                delta_spy = abs(new_target["SPY"] - drifted_spy_w)
                delta_gld = abs(new_target["GLD"] - drifted_gld_w)
                max_delta = max(delta_spy, delta_gld)
                if max_delta > threshold:
                    rebalance = True
            else:
                rebalance = True

        if rebalance:
            # Compute turnover (sum of absolute weight changes)
            turnover = (abs(new_target["SPY"] - drifted_spy_w) +
                       abs(new_target["GLD"] - drifted_gld_w) +
                       abs(new_target["CASH"] - drifted_cash_w))
            # TX cost: half of turnover * cost (since cost is round-trip per trade)
            tx_cost_today = turnover * tx_cost_frac / 2.0
            tx_costs_daily[i] = tx_cost_today

            current_spy_w = new_target["SPY"]
            current_gld_w = new_target["GLD"]
            current_cash_w = new_target["CASH"]
            trade_flags[i] = True
        else:
            # No rebalance: use drifted weights
            current_spy_w = drifted_spy_w
            current_gld_w = drifted_gld_w
            current_cash_w = drifted_cash_w
            tx_costs_daily[i] = 0.0

        # Portfolio return for day i (using current weights at start of day)
        port_returns[i] = (current_spy_w * spy_r[i] +
                          current_gld_w * gld_r[i] +
                          current_cash_w * 0.0 -  # cash return = 0
                          tx_costs_daily[i])

    # Compute metrics
    gross_returns = np.copy(port_returns)
    gross_returns += tx_costs_daily  # add back TX costs for gross returns

    ann_factor = 252
    n_years = T / ann_factor

    # Gross metrics
    gross_mean = np.mean(gross_returns) * ann_factor
    gross_std = np.std(gross_returns, ddof=1) * np.sqrt(ann_factor)
    gross_sharpe = gross_mean / gross_std if gross_std > 0 else 0

    # Net metrics (already in port_returns)
    net_mean = np.mean(port_returns) * ann_factor
    net_std = np.std(port_returns, ddof=1) * np.sqrt(ann_factor)
    net_sharpe = net_mean / net_std if net_std > 0 else 0

    # MDD
    cum_ret = np.cumprod(1 + port_returns)
    running_max = np.maximum.accumulate(cum_ret)
    drawdown = (cum_ret - running_max) / running_max
    mdd = float(np.min(drawdown))

    # Total cumulative return
    total_return = float(cum_ret[-1] / cum_ret[0] - 1)
    cagr = float((cum_ret[-1] / cum_ret[0]) ** (1 / n_years) - 1) if n_years > 0 else 0

    # Trade stats
    n_trades = int(np.sum(trade_flags))
    trades_per_year = n_trades / n_years if n_years > 0 else 0
    total_tx = float(np.sum(tx_costs_daily))
    annual_tx_drag = total_tx / n_years if n_years > 0 else 0

    # Tracking error vs daily benchmark (will compute separately)
    # Return daily returns for tracking error computation
    return {
        "rule": rebalance_rule,
        "threshold": threshold,
        "gross_sharpe": round(gross_sharpe, 4),
        "net_sharpe": round(net_sharpe, 4),
        "gross_return_ann": round(gross_mean, 4),
        "net_return_ann": round(net_mean, 4),
        "volatility_ann": round(net_std, 4),
        "mdd": round(mdd, 4),
        "total_return": round(total_return, 4),
        "cagr": round(cagr, 4),
        "n_trades": n_trades,
        "trades_per_year": round(trades_per_year, 1),
        "total_tx_cost": round(total_tx, 6),
        "annual_tx_drag_bp": round(annual_tx_drag * 10000, 2),
        "n_days": T,
        "n_years": round(n_years, 2),
        "daily_returns": port_returns.tolist(),  # for tracking error
        "gross_daily_returns": gross_returns.tolist(),
    }


# ============================================================================
# Tracking Error Computation
# ============================================================================
def compute_tracking_error(daily_returns_test, daily_returns_benchmark):
    """Compute annualized tracking error vs benchmark."""
    diff = np.array(daily_returns_test) - np.array(daily_returns_benchmark)
    te = float(np.std(diff, ddof=1) * np.sqrt(252))
    corr = float(np.corrcoef(daily_returns_test, daily_returns_benchmark)[0, 1])
    return te, corr


# ============================================================================
# Bootstrap Sharpe Difference Test
# ============================================================================
def bootstrap_sharpe_diff(returns_a, returns_b, n_boot=10000, seed=42):
    """
    Bootstrap test for Sharpe ratio difference.
    H0: Sharpe_a - Sharpe_b = 0
    Returns p-value (two-sided).
    """
    rng = np.random.RandomState(seed)
    returns_a = np.array(returns_a)
    returns_b = np.array(returns_b)
    T = len(returns_a)

    sharpe_a = np.mean(returns_a) / np.std(returns_a, ddof=1) * np.sqrt(252)
    sharpe_b = np.mean(returns_b) / np.std(returns_b, ddof=1) * np.sqrt(252)
    obs_diff = sharpe_a - sharpe_b

    # Center for null hypothesis
    centered_a = returns_a - np.mean(returns_a) + np.mean(np.concatenate([returns_a, returns_b])) / 2
    centered_b = returns_b - np.mean(returns_b) + np.mean(np.concatenate([returns_a, returns_b])) / 2

    boot_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, T, T)
        ba = centered_a[idx]
        bb = centered_b[idx]
        sa = np.mean(ba) / np.std(ba, ddof=1) * np.sqrt(252) if np.std(ba, ddof=1) > 0 else 0
        sb = np.mean(bb) / np.std(bb, ddof=1) * np.sqrt(252) if np.std(bb, ddof=1) > 0 else 0
        boot_diffs[b] = sa - sb

    p_value = float(np.mean(np.abs(boot_diffs) >= np.abs(obs_diff)))
    return obs_diff, p_value


# ============================================================================
# Main
# ============================================================================
def main():
    P(f"{'='*70}")
    P(f"K642: Optimal Rebalancing Frequency for VT Strategies")
    P(f"{'='*70}")
    P(f"Started: {datetime.now(timezone.utc).isoformat()}")
    P("")

    # ---- Data Download ----
    P("[1/6] Downloading data...")
    spy_df = download_data("SPY")
    gld_df = download_data("GLD")
    vix_series = download_vix()

    # Taiwan data
    P("  Downloading 0050.TW...")
    tw50_df = yf.download("0050.TW", start=DATA_START, end=DATA_END, progress=False)
    if isinstance(tw50_df.columns, pd.MultiIndex):
        tw50_df.columns = tw50_df.columns.get_level_values(0)
    tw50_df = tw50_df[["Close"]].dropna()
    tw50_df["return"] = np.log(tw50_df["Close"] / tw50_df["Close"].shift(1))
    tw50_df = tw50_df.dropna()

    # GLD for Taiwan portfolio (same GLD)
    P(f"  SPY: {len(spy_df)} days ({spy_df.index[0].date()} to {spy_df.index[-1].date()})")
    P(f"  GLD: {len(gld_df)} days ({gld_df.index[0].date()} to {gld_df.index[-1].date()})")
    P(f"  VIX: {len(vix_series)} days")
    P(f"  0050.TW: {len(tw50_df)} days ({tw50_df.index[0].date()} to {tw50_df.index[-1].date()})")

    # ---- OOS filter ----
    oos_mask_spy = (spy_df.index >= OOS_START) & (spy_df.index <= OOS_END)
    spy_oos = spy_df.loc[oos_mask_spy, "return"]

    oos_mask_gld = (gld_df.index >= OOS_START) & (gld_df.index <= OOS_END)
    gld_oos = gld_df.loc[oos_mask_gld, "return"]

    oos_mask_vix = (vix_series.index >= OOS_START) & (vix_series.index <= OOS_END)
    vix_oos = vix_series.loc[oos_mask_vix]

    oos_mask_tw = (tw50_df.index >= OOS_START) & (tw50_df.index <= OOS_END)
    tw50_oos = tw50_df.loc[oos_mask_tw, "return"]

    P(f"\n  OOS period: {OOS_START} to {OOS_END}")
    P(f"  SPY OOS days: {len(spy_oos)}")
    P(f"  0050.TW OOS days: {len(tw50_oos)}")

    # ---- Descriptive Stats ----
    P("\n[2/6] Descriptive statistics (OOS period)...")
    for name, ret_series in [("SPY", spy_oos), ("GLD", gld_oos), ("0050.TW", tw50_oos)]:
        P(f"\n  {name}:")
        P(f"    Mean daily return: {ret_series.mean():.6f}")
        P(f"    Std daily return:  {ret_series.std():.6f}")
        P(f"    Ann return:        {ret_series.mean()*252:.4f}")
        P(f"    Ann volatility:    {ret_series.std()*np.sqrt(252):.4f}")
        P(f"    Skewness:          {float(stats.skew(ret_series)):.4f}")
        P(f"    Kurtosis:          {float(stats.kurtosis(ret_series)):.4f}")
        P(f"    N:                 {len(ret_series)}")

    vix_oos_vals = vix_oos.values
    P(f"\n  VIX (OOS):")
    P(f"    Mean: {np.mean(vix_oos_vals):.2f}")
    P(f"    Std:  {np.std(vix_oos_vals):.2f}")
    P(f"    Min:  {np.min(vix_oos_vals):.2f}")
    P(f"    Max:  {np.max(vix_oos_vals):.2f}")

    # ============================================================================
    # Part A: US Market (SPY/GLD, 2bp TX cost)
    # ============================================================================
    P(f"\n{'='*70}")
    P("[3/6] Part A: US Market — Rebalancing Frequency Analysis")
    P(f"       Assets: SPY/GLD (50/50), TX cost: {TX_COST_US_BP}bp")
    P(f"{'='*70}")

    rebalance_rules = [
        ("daily", 0.0),
        ("weekly", 0.0),
        ("biweekly", 0.0),
        ("monthly", 0.0),
        ("quarterly", 0.0),
        ("semiannual", 0.0),
        ("annual", 0.0),
        ("threshold_5", 0.05),   # 5% weight change threshold
        ("threshold_10", 0.10),  # 10% weight change threshold
    ]

    us_results = []
    for rule, thresh in rebalance_rules:
        P(f"\n  Testing: {rule} (threshold={thresh:.0%})...")
        result = run_backtest(spy_oos, gld_oos, vix_oos, rule, TX_COST_US_BP, thresh)
        us_results.append(result)
        P(f"    Gross Sharpe: {result['gross_sharpe']:.4f}  |  Net Sharpe: {result['net_sharpe']:.4f}")
        P(f"    MDD: {result['mdd']:.4f}  |  Trades/yr: {result['trades_per_year']:.1f}")
        P(f"    Annual TX drag: {result['annual_tx_drag_bp']:.2f} bp")

    # Get daily returns as benchmark for tracking error
    daily_benchmark = us_results[0]["daily_returns"]  # daily rebalancing = benchmark

    P(f"\n  Computing tracking errors vs daily rebalancing...")
    for r in us_results:
        if r["rule"] == "daily":
            r["tracking_error_ann"] = 0.0
            r["corr_vs_daily"] = 1.0
        else:
            # Align lengths (should be same, but safeguard)
            min_len = min(len(r["daily_returns"]), len(daily_benchmark))
            te, corr = compute_tracking_error(
                r["daily_returns"][:min_len],
                daily_benchmark[:min_len]
            )
            r["tracking_error_ann"] = round(te, 4)
            r["corr_vs_daily"] = round(corr, 6)

    # Summary table
    P(f"\n{'='*70}")
    P("  US Market Results Summary (50/50 SPY/GLD, 12/VIX, 2bp TX)")
    P(f"{'='*70}")
    P(f"  {'Rule':<15} {'Gross SR':<10} {'Net SR':<10} {'MDD':<10} "
      f"{'Trades/yr':<12} {'TX bp/yr':<10} {'TE ann':<10} {'Corr':<8}")
    P(f"  {'-'*85}")
    for r in us_results:
        P(f"  {r['rule']:<15} {r['gross_sharpe']:<10.4f} {r['net_sharpe']:<10.4f} "
          f"{r['mdd']:<10.4f} {r['trades_per_year']:<12.1f} "
          f"{r['annual_tx_drag_bp']:<10.2f} {r['tracking_error_ann']:<10.4f} "
          f"{r['corr_vs_daily']:<8.4f}")

    # Find optimal
    best_net = max(us_results, key=lambda x: x["net_sharpe"])
    P(f"\n  ** Best NET Sharpe: {best_net['rule']} (Net SR={best_net['net_sharpe']:.4f})")

    # ---- Bootstrap test: best vs daily ----
    P(f"\n  Bootstrap test: {best_net['rule']} vs daily...")
    if best_net["rule"] != "daily":
        daily_rets = np.array(us_results[0]["daily_returns"])
        best_rets = np.array(best_net["daily_returns"])
        min_len = min(len(daily_rets), len(best_rets))
        diff, pval = bootstrap_sharpe_diff(best_rets[:min_len], daily_rets[:min_len])
        P(f"    Sharpe diff: {diff:.4f}, p-value: {pval:.4f}")
        us_bootstrap = {"diff": round(diff, 4), "p_value": round(pval, 4),
                        "comparison": f"{best_net['rule']} vs daily"}
    else:
        P(f"    Daily is already best — no test needed")
        us_bootstrap = {"diff": 0.0, "p_value": 1.0, "comparison": "daily vs daily"}

    # ---- Threshold analysis: what threshold keeps >95% of daily Sharpe? ----
    P(f"\n  Threshold sensitivity analysis...")
    daily_sharpe = us_results[0]["net_sharpe"]
    target_sharpe = daily_sharpe * 0.95
    P(f"    Daily Net Sharpe: {daily_sharpe:.4f}")
    P(f"    95% target: {target_sharpe:.4f}")

    thresholds_to_test = [0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25]
    threshold_results_us = []
    for thresh in thresholds_to_test:
        result = run_backtest(spy_oos, gld_oos, vix_oos, "threshold", TX_COST_US_BP, thresh)
        result["rule"] = f"threshold_{int(thresh*100)}"
        result["threshold"] = thresh
        threshold_results_us.append(result)
        meets_target = result["net_sharpe"] >= target_sharpe
        P(f"    Threshold {thresh:.0%}: Net SR={result['net_sharpe']:.4f}, "
          f"Trades/yr={result['trades_per_year']:.1f} {'✓' if meets_target else '✗'}")

    # Find min-trade threshold that still meets 95%
    valid_thresholds = [t for t in threshold_results_us if t["net_sharpe"] >= target_sharpe]
    if valid_thresholds:
        best_threshold = max(valid_thresholds, key=lambda x: x["threshold"])
        P(f"\n    ** Max threshold keeping >95% Sharpe: {best_threshold['threshold']:.0%}")
        P(f"       Net SR: {best_threshold['net_sharpe']:.4f}, Trades/yr: {best_threshold['trades_per_year']:.1f}")
    else:
        best_threshold = None
        P(f"\n    ** No threshold meets 95% Sharpe target")

    # ============================================================================
    # Part B: Taiwan Market (0050.TW + GLD, 18.5bp TX cost)
    # ============================================================================
    P(f"\n{'='*70}")
    P("[4/6] Part B: Taiwan Market — Rebalancing Frequency Analysis")
    P(f"       Assets: 0050.TW/GLD (50/50), TX cost: {TX_COST_TW_BP}bp")
    P(f"       Using 8.63/VIX (adjusted for VIXTWN ratio 1.39)")
    P(f"{'='*70}")

    # For Taiwan, we use 8.63/VIX instead of 12/VIX
    def compute_tw_target_weights(vix_level: float) -> dict:
        w = min(8.63 / vix_level, 1.0) if vix_level > 0 else 1.0
        return {
            "SPY": 0.5 * w,  # will actually be 0050.TW
            "GLD": 0.5 * w,
            "CASH": max(0, 1.0 - w),
        }

    # Override compute_target_weights for TW backtest
    # We need a custom backtest for Taiwan
    def run_tw_backtest(tw_ret, gld_ret, vix_s, rule, tx_bp, threshold=0.0):
        """Taiwan backtest using 8.63/VIX."""
        common_idx = tw_ret.index.intersection(gld_ret.index).intersection(vix_s.index)
        common_idx = common_idx.sort_values()

        tw_r = tw_ret.loc[common_idx].values
        gld_r = gld_ret.loc[common_idx].values
        vix_v = vix_s.loc[common_idx].values
        dates = common_idx
        T = len(dates)
        tx_cost_frac = tx_bp / 10000.0

        port_returns = np.zeros(T)
        trade_flags = np.zeros(T, dtype=bool)
        tx_costs_daily = np.zeros(T)

        def tw_weights(vix_level):
            w = min(8.63 / vix_level, 1.0) if vix_level > 0 else 1.0
            return {"TW": 0.5 * w, "GLD": 0.5 * w, "CASH": max(0, 1.0 - w)}

        target = tw_weights(vix_v[0])
        cur_tw_w = target["TW"]
        cur_gld_w = target["GLD"]
        cur_cash_w = target["CASH"]
        trade_flags[0] = True

        def is_rebalance_day(i, rl, dates_arr):
            if rl == 'daily':
                return True
            elif rl == 'weekly':
                return dates_arr[i].weekday() == 0
            elif rl == 'biweekly':
                if dates_arr[i].weekday() != 0:
                    return False
                days_diff = (dates_arr[i] - dates_arr[0]).days
                return (days_diff // 7) % 2 == 0
            elif rl == 'monthly':
                return i == 0 or dates_arr[i].month != dates_arr[i-1].month
            elif rl == 'quarterly':
                if i == 0:
                    return True
                return ((dates_arr[i].month-1)//3 != (dates_arr[i-1].month-1)//3 or
                        dates_arr[i].year != dates_arr[i-1].year)
            elif rl == 'semiannual':
                if i == 0:
                    return True
                ch = 0 if dates_arr[i].month <= 6 else 1
                ph = 0 if dates_arr[i-1].month <= 6 else 1
                return ch != ph or dates_arr[i].year != dates_arr[i-1].year
            elif rl == 'annual':
                return i == 0 or dates_arr[i].year != dates_arr[i-1].year
            elif rl.startswith('threshold'):
                return True
            return False

        for i in range(1, T):
            tw_growth = cur_tw_w * (1.0 + tw_r[i-1])
            gld_growth = cur_gld_w * (1.0 + gld_r[i-1])
            cash_growth = cur_cash_w * 1.0
            total = tw_growth + gld_growth + cash_growth

            if total > 0:
                d_tw_w = tw_growth / total
                d_gld_w = gld_growth / total
                d_cash_w = cash_growth / total
            else:
                d_tw_w, d_gld_w, d_cash_w = cur_tw_w, cur_gld_w, cur_cash_w

            new_t = tw_weights(vix_v[i])
            rebalance = False
            if is_rebalance_day(i, rule, dates):
                if rule.startswith('threshold'):
                    delta = max(abs(new_t["TW"] - d_tw_w), abs(new_t["GLD"] - d_gld_w))
                    if delta > threshold:
                        rebalance = True
                else:
                    rebalance = True

            if rebalance:
                turnover = (abs(new_t["TW"] - d_tw_w) + abs(new_t["GLD"] - d_gld_w) +
                           abs(new_t["CASH"] - d_cash_w))
                tx_costs_daily[i] = turnover * tx_cost_frac / 2.0
                cur_tw_w = new_t["TW"]
                cur_gld_w = new_t["GLD"]
                cur_cash_w = new_t["CASH"]
                trade_flags[i] = True
            else:
                cur_tw_w, cur_gld_w, cur_cash_w = d_tw_w, d_gld_w, d_cash_w

            port_returns[i] = (cur_tw_w * tw_r[i] + cur_gld_w * gld_r[i] - tx_costs_daily[i])

        gross_returns = port_returns + tx_costs_daily
        n_years = T / 252
        gross_sharpe = (np.mean(gross_returns)*252) / (np.std(gross_returns,ddof=1)*np.sqrt(252)) if np.std(gross_returns,ddof=1)>0 else 0
        net_sharpe = (np.mean(port_returns)*252) / (np.std(port_returns,ddof=1)*np.sqrt(252)) if np.std(port_returns,ddof=1)>0 else 0
        cum_ret = np.cumprod(1 + port_returns)
        running_max = np.maximum.accumulate(cum_ret)
        drawdown = (cum_ret - running_max) / running_max
        mdd = float(np.min(drawdown))
        total_return = float(cum_ret[-1] / cum_ret[0] - 1)
        cagr = float((cum_ret[-1] / cum_ret[0]) ** (1 / n_years) - 1) if n_years > 0 else 0
        n_trades = int(np.sum(trade_flags))
        trades_per_year = n_trades / n_years if n_years > 0 else 0
        total_tx = float(np.sum(tx_costs_daily))
        annual_tx_drag = total_tx / n_years if n_years > 0 else 0

        return {
            "rule": rule, "threshold": threshold,
            "gross_sharpe": round(gross_sharpe, 4), "net_sharpe": round(net_sharpe, 4),
            "gross_return_ann": round(float(np.mean(gross_returns)*252), 4),
            "net_return_ann": round(float(np.mean(port_returns)*252), 4),
            "volatility_ann": round(float(np.std(port_returns,ddof=1)*np.sqrt(252)), 4),
            "mdd": round(mdd, 4),
            "total_return": round(total_return, 4), "cagr": round(cagr, 4),
            "n_trades": n_trades, "trades_per_year": round(trades_per_year, 1),
            "total_tx_cost": round(total_tx, 6),
            "annual_tx_drag_bp": round(annual_tx_drag * 10000, 2),
            "n_days": T, "n_years": round(n_years, 2),
            "daily_returns": port_returns.tolist(),
            "gross_daily_returns": gross_returns.tolist(),
        }

    # Use previous-day VIX for Taiwan (VIX lag)
    vix_lagged = vix_series.shift(1).dropna()

    tw_results = []
    for rule, thresh in rebalance_rules:
        P(f"\n  Testing: {rule} (threshold={thresh:.0%})...")
        result = run_tw_backtest(tw50_oos, gld_oos, vix_lagged.loc[
            (vix_lagged.index >= OOS_START) & (vix_lagged.index <= OOS_END)
        ], rule, TX_COST_TW_BP, thresh)
        tw_results.append(result)
        P(f"    Gross Sharpe: {result['gross_sharpe']:.4f}  |  Net Sharpe: {result['net_sharpe']:.4f}")
        P(f"    MDD: {result['mdd']:.4f}  |  Trades/yr: {result['trades_per_year']:.1f}")
        P(f"    Annual TX drag: {result['annual_tx_drag_bp']:.2f} bp")

    # Tracking error for Taiwan
    tw_daily_benchmark = tw_results[0]["daily_returns"]
    for r in tw_results:
        if r["rule"] == "daily":
            r["tracking_error_ann"] = 0.0
            r["corr_vs_daily"] = 1.0
        else:
            min_len = min(len(r["daily_returns"]), len(tw_daily_benchmark))
            te, corr = compute_tracking_error(
                r["daily_returns"][:min_len], tw_daily_benchmark[:min_len])
            r["tracking_error_ann"] = round(te, 4)
            r["corr_vs_daily"] = round(corr, 6)

    # Summary table TW
    P(f"\n{'='*70}")
    P("  Taiwan Market Results Summary (50/50 0050.TW/GLD, 8.63/VIX, 18.5bp TX)")
    P(f"{'='*70}")
    P(f"  {'Rule':<15} {'Gross SR':<10} {'Net SR':<10} {'MDD':<10} "
      f"{'Trades/yr':<12} {'TX bp/yr':<10} {'TE ann':<10} {'Corr':<8}")
    P(f"  {'-'*85}")
    for r in tw_results:
        P(f"  {r['rule']:<15} {r['gross_sharpe']:<10.4f} {r['net_sharpe']:<10.4f} "
          f"{r['mdd']:<10.4f} {r['trades_per_year']:<12.1f} "
          f"{r['annual_tx_drag_bp']:<10.2f} {r['tracking_error_ann']:<10.4f} "
          f"{r['corr_vs_daily']:<8.4f}")

    best_tw_net = max(tw_results, key=lambda x: x["net_sharpe"])
    P(f"\n  ** Best NET Sharpe (TW): {best_tw_net['rule']} (Net SR={best_tw_net['net_sharpe']:.4f})")

    # Taiwan threshold analysis
    P(f"\n  Taiwan threshold sensitivity analysis...")
    tw_daily_sharpe = tw_results[0]["net_sharpe"]
    tw_target_sharpe = tw_daily_sharpe * 0.95
    P(f"    Daily Net Sharpe: {tw_daily_sharpe:.4f}")
    P(f"    95% target: {tw_target_sharpe:.4f}")

    threshold_results_tw = []
    for thresh in thresholds_to_test:
        result = run_tw_backtest(tw50_oos, gld_oos, vix_lagged.loc[
            (vix_lagged.index >= OOS_START) & (vix_lagged.index <= OOS_END)
        ], "threshold", TX_COST_TW_BP, thresh)
        result["rule"] = f"threshold_{int(thresh*100)}"
        result["threshold"] = thresh
        threshold_results_tw.append(result)
        meets_target = result["net_sharpe"] >= tw_target_sharpe
        P(f"    Threshold {thresh:.0%}: Net SR={result['net_sharpe']:.4f}, "
          f"Trades/yr={result['trades_per_year']:.1f} {'✓' if meets_target else '✗'}")

    valid_tw = [t for t in threshold_results_tw if t["net_sharpe"] >= tw_target_sharpe]
    if valid_tw:
        best_tw_thresh = max(valid_tw, key=lambda x: x["threshold"])
        P(f"\n    ** Max threshold keeping >95% Sharpe (TW): {best_tw_thresh['threshold']:.0%}")
        P(f"       Net SR: {best_tw_thresh['net_sharpe']:.4f}, Trades/yr: {best_tw_thresh['trades_per_year']:.1f}")
    else:
        best_tw_thresh = None
        P(f"\n    ** No threshold meets 95% Sharpe target (TW)")

    # ============================================================================
    # Part C: Comparative Analysis
    # ============================================================================
    P(f"\n{'='*70}")
    P("[5/6] Part C: Comparative Analysis")
    P(f"{'='*70}")

    # Key finding: TX cost impact comparison
    P(f"\n  TX cost impact comparison:")
    P(f"  {'Rule':<15} {'US Net SR':<12} {'US TX/yr':<12} {'TW Net SR':<12} {'TW TX/yr':<12} {'Gap':<8}")
    P(f"  {'-'*70}")
    for us_r, tw_r_item in zip(us_results, tw_results):
        gap = us_r["net_sharpe"] - tw_r_item["net_sharpe"]
        P(f"  {us_r['rule']:<15} {us_r['net_sharpe']:<12.4f} {us_r['annual_tx_drag_bp']:<12.2f} "
          f"{tw_r_item['net_sharpe']:<12.4f} {tw_r_item['annual_tx_drag_bp']:<12.2f} {gap:<8.4f}")

    # Gross-to-Net Sharpe degradation
    P(f"\n  Gross-to-Net Sharpe degradation:")
    P(f"  {'Rule':<15} {'US Gross':<10} {'US Net':<10} {'US Δ':<10} "
      f"{'TW Gross':<10} {'TW Net':<10} {'TW Δ':<10}")
    P(f"  {'-'*70}")
    for us_r, tw_r_item in zip(us_results, tw_results):
        us_delta = us_r["gross_sharpe"] - us_r["net_sharpe"]
        tw_delta = tw_r_item["gross_sharpe"] - tw_r_item["net_sharpe"]
        P(f"  {us_r['rule']:<15} {us_r['gross_sharpe']:<10.4f} {us_r['net_sharpe']:<10.4f} "
          f"{us_delta:<10.4f} {tw_r_item['gross_sharpe']:<10.4f} "
          f"{tw_r_item['net_sharpe']:<10.4f} {tw_delta:<10.4f}")

    # Calendar vs threshold comparison
    P(f"\n  Calendar vs Threshold comparison:")
    # For US: compare monthly calendar vs threshold_5
    us_monthly = next((r for r in us_results if r["rule"] == "monthly"), None)
    us_thresh5 = next((r for r in us_results if r["rule"] == "threshold_5"), None)
    if us_monthly and us_thresh5:
        P(f"    US: Monthly (Net SR={us_monthly['net_sharpe']:.4f}, {us_monthly['trades_per_year']:.1f} trades/yr) "
          f"vs Threshold 5% (Net SR={us_thresh5['net_sharpe']:.4f}, {us_thresh5['trades_per_year']:.1f} trades/yr)")
        calendar_better_us = us_monthly["net_sharpe"] >= us_thresh5["net_sharpe"]
        P(f"    → {'Calendar' if calendar_better_us else 'Threshold'} better for US")

    tw_monthly = next((r for r in tw_results if r["rule"] == "monthly"), None)
    tw_thresh5 = next((r for r in tw_results if r["rule"] == "threshold_5"), None)
    if tw_monthly and tw_thresh5:
        P(f"    TW: Monthly (Net SR={tw_monthly['net_sharpe']:.4f}, {tw_monthly['trades_per_year']:.1f} trades/yr) "
          f"vs Threshold 5% (Net SR={tw_thresh5['net_sharpe']:.4f}, {tw_thresh5['trades_per_year']:.1f} trades/yr)")
        calendar_better_tw = tw_monthly["net_sharpe"] >= tw_thresh5["net_sharpe"]
        P(f"    → {'Calendar' if calendar_better_tw else 'Threshold'} better for TW")

    # ============================================================================
    # Plots
    # ============================================================================
    P(f"\n{'='*70}")
    P("[6/6] Generating plots...")
    P(f"{'='*70}")

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("K642: Optimal Rebalancing Frequency for VT Strategies", fontsize=14, fontweight='bold')

    # Plot 1: Net Sharpe by frequency (US)
    ax1 = axes[0, 0]
    rules_labels = [r["rule"] for r in us_results]
    net_sharpes_us = [r["net_sharpe"] for r in us_results]
    colors = ['#2196F3' if r["rule"] == best_net["rule"] else '#90CAF9' for r in us_results]
    bars = ax1.bar(range(len(rules_labels)), net_sharpes_us, color=colors, edgecolor='#1565C0', linewidth=0.5)
    ax1.set_xticks(range(len(rules_labels)))
    ax1.set_xticklabels(rules_labels, rotation=45, ha='right', fontsize=8)
    ax1.set_ylabel("Net Sharpe Ratio")
    ax1.set_title(f"US: Net Sharpe by Rebalancing Rule ({TX_COST_US_BP}bp TX)")
    ax1.axhline(y=daily_sharpe * 0.95, color='red', linestyle='--', alpha=0.5, label='95% of daily')
    ax1.legend(fontsize=8)
    ax1.grid(axis='y', alpha=0.3)

    # Plot 2: Net Sharpe by frequency (Taiwan)
    ax2 = axes[0, 1]
    net_sharpes_tw = [r["net_sharpe"] for r in tw_results]
    colors_tw = ['#4CAF50' if r["rule"] == best_tw_net["rule"] else '#A5D6A7' for r in tw_results]
    ax2.bar(range(len(rules_labels)), net_sharpes_tw, color=colors_tw, edgecolor='#2E7D32', linewidth=0.5)
    ax2.set_xticks(range(len(rules_labels)))
    ax2.set_xticklabels(rules_labels, rotation=45, ha='right', fontsize=8)
    ax2.set_ylabel("Net Sharpe Ratio")
    ax2.set_title(f"Taiwan: Net Sharpe by Rebalancing Rule ({TX_COST_TW_BP}bp TX)")
    ax2.axhline(y=tw_daily_sharpe * 0.95, color='red', linestyle='--', alpha=0.5, label='95% of daily')
    ax2.legend(fontsize=8)
    ax2.grid(axis='y', alpha=0.3)

    # Plot 3: Trades/yr vs Net Sharpe (both markets)
    ax3 = axes[1, 0]
    trades_us = [r["trades_per_year"] for r in us_results]
    trades_tw = [r["trades_per_year"] for r in tw_results]
    ax3.scatter(trades_us, net_sharpes_us, color='#2196F3', s=80, label='US (2bp)', zorder=5, edgecolors='#1565C0')
    ax3.scatter(trades_tw, net_sharpes_tw, color='#4CAF50', s=80, label='TW (18.5bp)', zorder=5, edgecolors='#2E7D32')
    for i, r in enumerate(us_results):
        ax3.annotate(r["rule"], (trades_us[i], net_sharpes_us[i]),
                    fontsize=6, ha='center', va='bottom', color='#1565C0')
    for i, r in enumerate(tw_results):
        ax3.annotate(r["rule"], (trades_tw[i], net_sharpes_tw[i]),
                    fontsize=6, ha='center', va='bottom', color='#2E7D32')
    ax3.set_xlabel("Trades per Year")
    ax3.set_ylabel("Net Sharpe Ratio")
    ax3.set_title("Efficiency Frontier: Trades vs Net Sharpe")
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.3)

    # Plot 4: TX cost drag comparison
    ax4 = axes[1, 1]
    tx_us = [r["annual_tx_drag_bp"] for r in us_results]
    tx_tw = [r["annual_tx_drag_bp"] for r in tw_results]
    x_pos = np.arange(len(rules_labels))
    width = 0.35
    ax4.bar(x_pos - width/2, tx_us, width, label=f'US ({TX_COST_US_BP}bp)', color='#2196F3', alpha=0.8)
    ax4.bar(x_pos + width/2, tx_tw, width, label=f'TW ({TX_COST_TW_BP}bp)', color='#4CAF50', alpha=0.8)
    ax4.set_xticks(x_pos)
    ax4.set_xticklabels(rules_labels, rotation=45, ha='right', fontsize=8)
    ax4.set_ylabel("Annual TX Cost Drag (bp)")
    ax4.set_title("Transaction Cost Drag by Frequency")
    ax4.legend(fontsize=8)
    ax4.grid(axis='y', alpha=0.3)

    plt.tight_layout()
    plot_path = BASE_DIR / "k642_rebalance_frequency.png"
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    plt.close()
    P(f"  Saved plot: {plot_path}")

    # ============================================================================
    # Save Results
    # ============================================================================
    elapsed = time.time() - START_TIME

    # Clean up daily_returns from results for JSON (too large)
    def clean_result(r):
        return {k: v for k, v in r.items() if k not in ("daily_returns", "gross_daily_returns")}

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Optimal Rebalancing Frequency for VT Strategies",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "data_source": "yfinance",
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "analysis_type": "empirical",
        "strategy": "50/50 SPY/GLD with 12/VIX (US) / 50/50 0050.TW/GLD with 8.63/VIX (TW)",
        "methodology": "Calendar-based and threshold-based rebalancing frequency comparison",
        "references": [
            "DeMiguel, Garlappi & Uppal (2009) RFS",
            "Kirby & Ostdiek (2012) JFE",
            "Masters (2003) JPM",
            "Tokat & Wicas (2007) JPM",
            "Fleming, Kirby & Ostdiek (2003) JFE",
        ],
        "us_market": {
            "assets": "SPY/GLD",
            "tx_cost_bp": TX_COST_US_BP,
            "results": [clean_result(r) for r in us_results],
            "best_net_sharpe_rule": best_net["rule"],
            "best_net_sharpe": best_net["net_sharpe"],
            "bootstrap_test": us_bootstrap,
            "threshold_sensitivity": [clean_result(t) for t in threshold_results_us],
            "best_threshold_95pct": {
                "threshold": best_threshold["threshold"] if best_threshold else None,
                "net_sharpe": best_threshold["net_sharpe"] if best_threshold else None,
                "trades_per_year": best_threshold["trades_per_year"] if best_threshold else None,
            },
        },
        "taiwan_market": {
            "assets": "0050.TW/GLD",
            "tx_cost_bp": TX_COST_TW_BP,
            "vix_adjustment": "8.63/VIX (= 12/VIX * 1/1.39, VIXTWN ratio)",
            "vix_lag": "previous day VIX used for Taiwan",
            "results": [clean_result(r) for r in tw_results],
            "best_net_sharpe_rule": best_tw_net["rule"],
            "best_net_sharpe": best_tw_net["net_sharpe"],
            "threshold_sensitivity": [clean_result(t) for t in threshold_results_tw],
            "best_threshold_95pct": {
                "threshold": best_tw_thresh["threshold"] if best_tw_thresh else None,
                "net_sharpe": best_tw_thresh["net_sharpe"] if best_tw_thresh else None,
                "trades_per_year": best_tw_thresh["trades_per_year"] if best_tw_thresh else None,
            },
        },
        "key_findings": [],
        "limitations": [
            "Cash return assumed 0 (no risk-free rate modeled)",
            "Transaction cost is symmetric (same for buy/sell)",
            "No slippage or market impact modeled",
            "VIX used as real-time (no intraday lag within US)",
            "Taiwan uses previous-day VIX (1-day lag)",
            "OOS period 2010-2026 includes specific market regimes",
            "Single asset pair tested per market",
        ],
        "plot_path": str(RELATIVE_DIR / plot_path.name),
    }

    # Compute key findings
    findings = []

    # Finding 1: US daily vs others
    us_daily_sr = us_results[0]["net_sharpe"]
    us_annual_sr = next(r["net_sharpe"] for r in us_results if r["rule"] == "annual")
    us_monthly_sr = next(r["net_sharpe"] for r in us_results if r["rule"] == "monthly")
    findings.append(
        f"US market (2bp TX): Daily rebalancing Net Sharpe = {us_daily_sr:.4f}. "
        f"Monthly = {us_monthly_sr:.4f}. Annual = {us_annual_sr:.4f}. "
        f"Best rule = {best_net['rule']} (Net SR={best_net['net_sharpe']:.4f})."
    )

    # Finding 2: TW impact
    tw_daily_sr_val = tw_results[0]["net_sharpe"]
    tw_monthly_sr = next(r["net_sharpe"] for r in tw_results if r["rule"] == "monthly")
    findings.append(
        f"Taiwan market (18.5bp TX): Daily rebalancing Net Sharpe = {tw_daily_sr_val:.4f}. "
        f"Monthly = {tw_monthly_sr:.4f}. "
        f"Best rule = {best_tw_net['rule']} (Net SR={best_tw_net['net_sharpe']:.4f}). "
        f"TX cost impact is {TX_COST_TW_BP/TX_COST_US_BP:.1f}x higher than US."
    )

    # Finding 3: TX drag comparison
    us_daily_drag = us_results[0]["annual_tx_drag_bp"]
    tw_daily_drag = tw_results[0]["annual_tx_drag_bp"]
    findings.append(
        f"Annual TX cost drag for daily rebalancing: US = {us_daily_drag:.2f} bp/yr, "
        f"TW = {tw_daily_drag:.2f} bp/yr ({tw_daily_drag/us_daily_drag:.1f}x)."
    )

    # Finding 4: Threshold vs calendar
    findings.append(
        f"Threshold-based rebalancing: US best threshold keeping >95% Sharpe = "
        f"{best_threshold['threshold']:.0%} ({best_threshold['trades_per_year']:.1f} trades/yr)" if best_threshold else
        "US: No threshold meets 95% Sharpe target"
    )
    findings.append(
        f"Threshold-based rebalancing: TW best threshold keeping >95% Sharpe = "
        f"{best_tw_thresh['threshold']:.0%} ({best_tw_thresh['trades_per_year']:.1f} trades/yr)" if best_tw_thresh else
        "TW: No threshold meets 95% Sharpe target"
    )

    # Finding 5: Gross-to-Net degradation
    us_daily_gross = us_results[0]["gross_sharpe"]
    tw_daily_gross = tw_results[0]["gross_sharpe"]
    findings.append(
        f"Gross-to-Net Sharpe degradation (daily): US = {us_daily_gross - us_daily_sr:.4f}, "
        f"TW = {tw_daily_gross - tw_daily_sr_val:.4f}."
    )

    results["key_findings"] = findings

    # Save
    results_path = BASE_DIR / "k642_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    P(f"\n  Saved results: {results_path}")

    # Print summary
    P(f"\n{'='*70}")
    P(f"K642 COMPLETE — Elapsed: {elapsed:.1f}s")
    P(f"{'='*70}")
    P(f"\nKey Findings:")
    for i, finding in enumerate(findings, 1):
        P(f"  {i}. {finding}")

    P(f"\nConclusion:")
    if best_net["rule"] == "daily":
        P(f"  US: Daily rebalancing is optimal — 2bp TX cost is negligible.")
    else:
        P(f"  US: {best_net['rule']} rebalancing is optimal (Net SR={best_net['net_sharpe']:.4f}).")

    if best_tw_net["rule"] == "daily":
        P(f"  TW: Even with 18.5bp TX, daily rebalancing is still optimal!")
    else:
        P(f"  TW: {best_tw_net['rule']} is optimal — high TX cost ({TX_COST_TW_BP}bp) penalizes frequent trading.")

    P(f"\n  Files saved:")
    P(f"    Script: experiments/k642/k642_rebalance_frequency.py")
    P(f"    Results: experiments/k642/k642_results.json")
    P(f"    Plot: experiments/k642/k642_rebalance_frequency.png")


if __name__ == "__main__":
    main()
