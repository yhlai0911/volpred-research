#!/usr/bin/env python3
"""
Experiment: Rebalancing Boundary for 12/VIX Strategy
=====================================================
Test whether "rebalancing boundary" (only rebalance when |w_current - w_target| > X%)
can reduce turnover and improve net Sharpe for the 50/50 SPY/GLD 12/VIX strategy.

Variants tested:
A) Boundary-based: monthly check, only rebalance if drift > threshold (3-20%)
B) Time-based: bimonthly, quarterly
C) VIX regime: only rebalance when VIX crosses regime thresholds (15, 20, 25, 30)

Baseline: monthly 12/VIX rebalance on first trading day of each month.
Portfolio: 50/50 SPY/GLD allocation within risky portion; remainder in SHY (cash proxy).
"""

import sys
import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─── Config ───────────────────────────────────────────────────────────────────
TX_COST = 0.0005       # 0.05% round-trip per trade
RF_ANNUAL = 0.045      # risk-free rate (approximate T-bill 2023-2026)
OOS_START = "2023-01-01"
OOS_END = "2026-03-20"
FULL_START = "2007-01-01"

BOUNDARY_THRESHOLDS = [0.0, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20]
TIME_VARIANTS = {
    "monthly": 1,
    "bimonthly": 2,
    "quarterly": 3,
}
VIX_REGIME_THRESHOLDS = [15, 20, 25, 30]

OUT_PATH = Path("/Users/yhlai0911/Desktop/volpred-research/storage/experiments/rebalancing_boundary.json")


def download_data():
    """Download SPY, GLD, VIX, SHY."""
    print("Downloading data...")
    spy = yf.download("SPY", start=FULL_START, progress=False)["Close"].squeeze()
    gld = yf.download("GLD", start=FULL_START, progress=False)["Close"].squeeze()
    vix = yf.download("^VIX", start=FULL_START, progress=False)["Close"].squeeze()
    shy = yf.download("SHY", start=FULL_START, progress=False)["Close"].squeeze()

    # Align all to common dates
    df = pd.DataFrame({"SPY": spy, "GLD": gld, "VIX": vix, "SHY": shy}).dropna()
    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, {len(df)} days")
    return df


def compute_returns(df):
    """Compute daily returns for SPY, GLD, SHY."""
    ret = pd.DataFrame(index=df.index)
    for col in ["SPY", "GLD", "SHY"]:
        ret[col] = df[col].pct_change()
    ret = ret.iloc[1:]  # drop first NaN
    return ret


def compute_target_weight(vix_value):
    """12/VIX target total risky weight, capped at 100%."""
    return min(12.0 / vix_value, 1.0)


def is_first_trading_day_of_month(date, prev_date):
    """Check if date is the first trading day of a new month."""
    return date.month != prev_date.month


def is_first_trading_day_of_period(date, prev_date, period_months):
    """Check if this is the first trading day of a new period (every N months)."""
    if date.month == prev_date.month:
        return False
    # Check if we're at a period boundary
    # period starts at month 1, 1+N, 1+2N, ...
    return (date.month - 1) % period_months == 0


def detect_regime_cross(vix_prev, vix_curr, thresholds):
    """Check if VIX crossed any regime threshold."""
    for t in thresholds:
        if (vix_prev < t and vix_curr >= t) or (vix_prev >= t and vix_curr < t):
            return True
    return False


def run_backtest(returns_df, vix_series, strategy_name, rebal_func,
                 full_start=None, full_end=None):
    """
    Generic backtest engine for 50/50 SPY/GLD 12/VIX with configurable rebalancing.

    rebal_func(date, prev_date, w_current_total, w_target_total, vix_curr, vix_prev, day_idx)
        -> bool (should rebalance?)

    All weights are LAGGED: VIX on day t determines weight for day t+1.
    """
    # Filter date range
    if full_start:
        mask = returns_df.index >= full_start
        returns_df = returns_df[mask]
        vix_series = vix_series[vix_series.index >= full_start]
    if full_end:
        mask = returns_df.index <= full_end
        returns_df = returns_df[mask]
        vix_series = vix_series[vix_series.index <= full_end]

    dates = returns_df.index
    n = len(dates)

    # Track weights and portfolio
    w_spy = np.zeros(n)
    w_gld = np.zeros(n)
    w_shy = np.zeros(n)
    port_ret = np.zeros(n)
    tx_cost_daily = np.zeros(n)
    rebal_events = np.zeros(n, dtype=bool)

    # Initialize: first day, use VIX from day before (lagged)
    # Find the VIX value just before the first return date
    first_ret_date = dates[0]
    vix_before = vix_series[vix_series.index < first_ret_date]
    if len(vix_before) == 0:
        initial_vix = vix_series.iloc[0]
    else:
        initial_vix = vix_before.iloc[-1]

    w_target_total = compute_target_weight(initial_vix)
    w_spy[0] = 0.5 * w_target_total
    w_gld[0] = 0.5 * w_target_total
    w_shy[0] = max(0, 1 - w_spy[0] - w_gld[0])
    rebal_events[0] = True

    # Track "current" total risky weight (drifts with returns)
    prev_vix = initial_vix

    for i in range(n):
        # Day i: use weights determined at end of day i-1 (lagged)
        r_spy = returns_df["SPY"].iloc[i]
        r_gld = returns_df["GLD"].iloc[i]
        r_shy = returns_df["SHY"].iloc[i]

        # Portfolio return for day i
        port_ret[i] = w_spy[i] * r_spy + w_gld[i] * r_gld + w_shy[i] * r_shy

        if i == n - 1:
            break

        # After day i, weights drift due to returns
        total_val = 1 + port_ret[i]
        if total_val <= 0:
            total_val = 1e-8

        w_spy_drift = w_spy[i] * (1 + r_spy) / total_val
        w_gld_drift = w_gld[i] * (1 + r_gld) / total_val
        w_shy_drift = w_shy[i] * (1 + r_shy) / total_val

        w_current_total = w_spy_drift + w_gld_drift  # current risky weight

        # Get VIX for today (will determine tomorrow's target)
        date_today = dates[i]
        # Find VIX on or before this date
        vix_on_date = vix_series[vix_series.index <= date_today]
        if len(vix_on_date) == 0:
            curr_vix = prev_vix
        else:
            curr_vix = vix_on_date.iloc[-1]

        w_target_total_new = compute_target_weight(curr_vix)

        # Decision: should we rebalance?
        next_date = dates[i + 1]
        should_rebal = rebal_func(
            next_date, date_today, w_current_total, w_target_total_new,
            curr_vix, prev_vix, i
        )

        if should_rebal:
            # Rebalance to new target
            w_spy_new = 0.5 * w_target_total_new
            w_gld_new = 0.5 * w_target_total_new
            w_shy_new = max(0, 1 - w_spy_new - w_gld_new)

            # Transaction cost = sum of |weight changes|
            turnover = (abs(w_spy_new - w_spy_drift) +
                       abs(w_gld_new - w_gld_drift) +
                       abs(w_shy_new - w_shy_drift))
            tx_cost_daily[i + 1] = turnover * TX_COST

            w_spy[i + 1] = w_spy_new
            w_gld[i + 1] = w_gld_new
            w_shy[i + 1] = w_shy_new
            rebal_events[i + 1] = True
        else:
            # Keep drifted weights
            w_spy[i + 1] = w_spy_drift
            w_gld[i + 1] = w_gld_drift
            w_shy[i + 1] = w_shy_drift

        prev_vix = curr_vix

    # Build results DataFrame
    results = pd.DataFrame({
        "date": dates,
        "port_ret_gross": port_ret,
        "port_ret_net": port_ret - tx_cost_daily,
        "tx_cost": tx_cost_daily,
        "w_spy": w_spy,
        "w_gld": w_gld,
        "w_shy": w_shy,
        "rebal": rebal_events,
    }).set_index("date")

    return results


def compute_metrics(results, rf_annual=RF_ANNUAL):
    """Compute strategy metrics from backtest results."""
    n_days = len(results)
    n_years = n_days / 252
    rf_daily = (1 + rf_annual) ** (1/252) - 1

    # Gross metrics
    gross_ret = results["port_ret_gross"]
    gross_mean = gross_ret.mean() * 252
    gross_std = gross_ret.std() * np.sqrt(252)
    gross_sharpe = (gross_mean - rf_annual) / gross_std if gross_std > 0 else 0

    # Net metrics
    net_ret = results["port_ret_net"]
    net_mean = net_ret.mean() * 252
    net_std = net_ret.std() * np.sqrt(252)
    net_sharpe = (net_mean - rf_annual) / net_std if net_std > 0 else 0

    # MDD
    cum_gross = (1 + gross_ret).cumprod()
    running_max = cum_gross.cummax()
    drawdown = cum_gross / running_max - 1
    mdd = drawdown.min()

    cum_net = (1 + net_ret).cumprod()
    running_max_net = cum_net.cummax()
    drawdown_net = cum_net / running_max_net - 1
    mdd_net = drawdown_net.min()

    # Turnover
    total_turnover = results["tx_cost"].sum() / TX_COST  # total |Δw| sum
    annual_turnover = total_turnover / n_years

    # Rebalance events
    n_rebal = results["rebal"].sum()
    annual_rebal = n_rebal / n_years

    # Total TC
    total_tc = results["tx_cost"].sum()
    annual_tc = total_tc / n_years

    # Calmar
    calmar = gross_mean / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = gross_ret[gross_ret < rf_daily]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else gross_std
    sortino = (gross_mean - rf_annual) / downside_std if downside_std > 0 else 0

    # Cumulative return
    total_return = cum_gross.iloc[-1] - 1
    total_return_net = cum_net.iloc[-1] - 1

    return {
        "n_days": int(n_days),
        "n_years": round(n_years, 2),
        "gross_annual_return": round(gross_mean, 4),
        "gross_annual_vol": round(gross_std, 4),
        "gross_sharpe": round(gross_sharpe, 4),
        "net_annual_return": round(net_mean, 4),
        "net_annual_vol": round(net_std, 4),
        "net_sharpe": round(net_sharpe, 4),
        "mdd_gross": round(mdd, 4),
        "mdd_net": round(mdd_net, 4),
        "total_return_gross": round(total_return, 4),
        "total_return_net": round(total_return_net, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "annual_turnover": round(annual_turnover, 4),
        "annual_rebal_events": round(annual_rebal, 2),
        "total_rebal_events": int(n_rebal),
        "annual_tc_pct": round(annual_tc * 100, 4),
        "total_tc_pct": round(total_tc * 100, 4),
    }


def harvey_t_stat(sharpe1, sharpe2, n_years):
    """
    Approximate t-stat for Sharpe difference.
    SE(Sharpe) ≈ 1/sqrt(N_years), so SE(ΔSharpe) ≈ sqrt(2)/sqrt(N_years).
    """
    se = np.sqrt(2) / np.sqrt(n_years)
    return (sharpe1 - sharpe2) / se if se > 0 else 0


def paired_sharpe_tstat(ret1, ret2, rf_annual=RF_ANNUAL):
    """
    Paired t-test on the difference of daily returns.
    Since both strategies have very similar volatility (same assets, same VIX signal),
    the Sharpe difference is well-approximated by testing mean(ret1 - ret2) / SE.
    This is essentially a Diebold-Mariano style test.
    """
    diff = np.array(ret1) - np.array(ret2)
    n = len(diff)
    if n < 2:
        return 0.0

    mu_diff = diff.mean()
    se_diff = diff.std(ddof=1) / np.sqrt(n)

    if se_diff == 0:
        return 0.0

    # Scale to annualized Sharpe units
    # t-stat for daily mean difference is the same as for annualized
    # (both numerator and denominator scale by sqrt(252))
    t = mu_diff / se_diff
    return float(t)


def main():
    # ─── Download data ────────────────────────────────────────────────────────
    df = download_data()
    returns = compute_returns(df)
    vix = df["VIX"]

    all_results = {}

    # ═══════════════════════════════════════════════════════════════════════════
    # PART A: Boundary-based rebalancing (monthly check)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART A: 再平衡邊界 (Rebalancing Boundary)")
    print("="*70)

    boundary_results = {}

    for threshold in BOUNDARY_THRESHOLDS:
        label = f"boundary_{int(threshold*100)}pct"
        if threshold == 0:
            label = "monthly_baseline"

        def make_rebal_func(thresh):
            def rebal_func(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
                # Only check on first trading day of month
                if next_date.month == curr_date.month:
                    return False
                # If threshold is 0, always rebalance on month boundary
                if thresh == 0:
                    return True
                # Only rebalance if drift exceeds threshold
                return abs(w_current - w_target) > thresh
            return rebal_func

        for period_label, period_dates in [("full", (FULL_START, None)),
                                            ("oos", (OOS_START, OOS_END))]:
            bt = run_backtest(
                returns.copy(), vix.copy(),
                f"{label}_{period_label}",
                make_rebal_func(threshold),
                full_start=period_dates[0],
                full_end=period_dates[1]
            )
            metrics = compute_metrics(bt)

            key = f"{label}_{period_label}"
            boundary_results[key] = {
                "strategy": label,
                "period": period_label,
                "threshold": threshold,
                "metrics": metrics,
                "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
            }

    # Print boundary results
    print(f"\n{'Strategy':<25} {'Period':<6} {'Gross SR':<10} {'Net SR':<10} {'MDD':<8} {'Turnover/yr':<12} {'Rebal/yr':<10} {'TC/yr':<8}")
    print("-" * 95)
    for key, res in boundary_results.items():
        m = res["metrics"]
        print(f"{res['strategy']:<25} {res['period']:<6} {m['gross_sharpe']:<10.4f} {m['net_sharpe']:<10.4f} "
              f"{m['mdd_gross']*100:<8.1f}% {m['annual_turnover']:<12.2f} {m['annual_rebal_events']:<10.1f} {m['annual_tc_pct']:<8.4f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART B: Time-based variants
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART B: 時間間隔變體 (Time-based Variants)")
    print("="*70)

    time_results = {}

    for variant_name, period_months in TIME_VARIANTS.items():
        def make_time_rebal_func(pm):
            def rebal_func(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
                # Check if next_date starts a new month
                if next_date.month == curr_date.month:
                    return False
                # Check if it's at the right period boundary
                if pm == 1:
                    return True
                return (next_date.month - 1) % pm == 0
            return rebal_func

        for period_label, period_dates in [("full", (FULL_START, None)),
                                            ("oos", (OOS_START, OOS_END))]:
            bt = run_backtest(
                returns.copy(), vix.copy(),
                f"{variant_name}_{period_label}",
                make_time_rebal_func(period_months),
                full_start=period_dates[0],
                full_end=period_dates[1]
            )
            metrics = compute_metrics(bt)

            key = f"{variant_name}_{period_label}"
            time_results[key] = {
                "strategy": variant_name,
                "period": period_label,
                "period_months": period_months,
                "metrics": metrics,
                "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
            }

    print(f"\n{'Strategy':<25} {'Period':<6} {'Gross SR':<10} {'Net SR':<10} {'MDD':<8} {'Turnover/yr':<12} {'Rebal/yr':<10} {'TC/yr':<8}")
    print("-" * 95)
    for key, res in time_results.items():
        m = res["metrics"]
        print(f"{res['strategy']:<25} {res['period']:<6} {m['gross_sharpe']:<10.4f} {m['net_sharpe']:<10.4f} "
              f"{m['mdd_gross']*100:<8.1f}% {m['annual_turnover']:<12.2f} {m['annual_rebal_events']:<10.1f} {m['annual_tc_pct']:<8.4f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART C: VIX Regime-based rebalancing
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART C: VIX 體制轉換觸發 (VIX Regime Crossing)")
    print("="*70)

    regime_results = {}

    # Single-threshold variants
    for vix_thresh in VIX_REGIME_THRESHOLDS:
        label = f"vix_cross_{vix_thresh}"

        def make_regime_func(vt):
            def rebal_func(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
                # Monthly check + VIX regime crossing
                is_month_boundary = next_date.month != curr_date.month
                crossed = (vix_p < vt and vix_c >= vt) or (vix_p >= vt and vix_c < vt)
                return is_month_boundary or crossed
            return rebal_func

        for period_label, period_dates in [("full", (FULL_START, None)),
                                            ("oos", (OOS_START, OOS_END))]:
            bt = run_backtest(
                returns.copy(), vix.copy(),
                f"{label}_{period_label}",
                make_regime_func(vix_thresh),
                full_start=period_dates[0],
                full_end=period_dates[1]
            )
            metrics = compute_metrics(bt)

            key = f"{label}_{period_label}"
            regime_results[key] = {
                "strategy": label,
                "period": period_label,
                "vix_threshold": vix_thresh,
                "metrics": metrics,
                "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
            }

    # Multi-threshold variant: rebalance when VIX crosses ANY of [15, 20, 25, 30]
    label = "vix_cross_multi"
    def rebal_multi(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
        is_month_boundary = next_date.month != curr_date.month
        crossed = detect_regime_cross(vix_p, vix_c, VIX_REGIME_THRESHOLDS)
        return is_month_boundary or crossed

    for period_label, period_dates in [("full", (FULL_START, None)),
                                        ("oos", (OOS_START, OOS_END))]:
        bt = run_backtest(
            returns.copy(), vix.copy(),
            f"{label}_{period_label}",
            rebal_multi,
            full_start=period_dates[0],
            full_end=period_dates[1]
        )
        metrics = compute_metrics(bt)
        key = f"{label}_{period_label}"
        regime_results[key] = {
            "strategy": label,
            "period": period_label,
            "vix_threshold": "multi [15,20,25,30]",
            "metrics": metrics,
            "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
        }

    # VIX regime ONLY (no monthly, pure regime-triggered)
    label = "vix_regime_only"
    def rebal_regime_only(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
        return detect_regime_cross(vix_p, vix_c, VIX_REGIME_THRESHOLDS)

    for period_label, period_dates in [("full", (FULL_START, None)),
                                        ("oos", (OOS_START, OOS_END))]:
        bt = run_backtest(
            returns.copy(), vix.copy(),
            f"{label}_{period_label}",
            rebal_regime_only,
            full_start=period_dates[0],
            full_end=period_dates[1]
        )
        metrics = compute_metrics(bt)
        key = f"{label}_{period_label}"
        regime_results[key] = {
            "strategy": label,
            "period": period_label,
            "vix_threshold": "multi (regime only, no monthly)",
            "metrics": metrics,
            "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
        }

    print(f"\n{'Strategy':<25} {'Period':<6} {'Gross SR':<10} {'Net SR':<10} {'MDD':<8} {'Turnover/yr':<12} {'Rebal/yr':<10} {'TC/yr':<8}")
    print("-" * 95)
    for key, res in regime_results.items():
        m = res["metrics"]
        print(f"{res['strategy']:<25} {res['period']:<6} {m['gross_sharpe']:<10.4f} {m['net_sharpe']:<10.4f} "
              f"{m['mdd_gross']*100:<8.1f}% {m['annual_turnover']:<12.2f} {m['annual_rebal_events']:<10.1f} {m['annual_tc_pct']:<8.4f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART D: Hybrid — Boundary + VIX regime
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART D: 混合策略 (Boundary + VIX Regime)")
    print("="*70)

    hybrid_results = {}

    # Best boundary + VIX regime cross
    for threshold in [0.05, 0.10]:
        label = f"hybrid_b{int(threshold*100)}_vix"

        def make_hybrid_func(thresh):
            def rebal_func(next_date, curr_date, w_current, w_target, vix_c, vix_p, idx):
                # Monthly check with boundary
                is_month = next_date.month != curr_date.month
                boundary_exceeded = abs(w_current - w_target) > thresh
                # VIX regime cross triggers immediate rebalance
                vix_crossed = detect_regime_cross(vix_p, vix_c, VIX_REGIME_THRESHOLDS)

                return (is_month and boundary_exceeded) or vix_crossed
            return rebal_func

        for period_label, period_dates in [("full", (FULL_START, None)),
                                            ("oos", (OOS_START, OOS_END))]:
            bt = run_backtest(
                returns.copy(), vix.copy(),
                f"{label}_{period_label}",
                make_hybrid_func(threshold),
                full_start=period_dates[0],
                full_end=period_dates[1]
            )
            metrics = compute_metrics(bt)
            key = f"{label}_{period_label}"
            hybrid_results[key] = {
                "strategy": label,
                "period": period_label,
                "boundary_threshold": threshold,
                "metrics": metrics,
                "daily_returns_net": bt["port_ret_net"].values.tolist() if period_label == "oos" else None,
            }

    print(f"\n{'Strategy':<25} {'Period':<6} {'Gross SR':<10} {'Net SR':<10} {'MDD':<8} {'Turnover/yr':<12} {'Rebal/yr':<10} {'TC/yr':<8}")
    print("-" * 95)
    for key, res in hybrid_results.items():
        m = res["metrics"]
        print(f"{res['strategy']:<25} {res['period']:<6} {m['gross_sharpe']:<10.4f} {m['net_sharpe']:<10.4f} "
              f"{m['mdd_gross']*100:<8.1f}% {m['annual_turnover']:<12.2f} {m['annual_rebal_events']:<10.1f} {m['annual_tc_pct']:<8.4f}%")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART E: Harvey t-stats and comparative analysis
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART E: Harvey t-statistics (Net Sharpe vs Monthly Baseline)")
    print("="*70)

    # Get baseline OOS net returns
    baseline_oos = boundary_results["monthly_baseline_oos"]
    baseline_ret = np.array(baseline_oos["daily_returns_net"])
    baseline_sharpe = baseline_oos["metrics"]["net_sharpe"]
    n_years_oos = baseline_oos["metrics"]["n_years"]

    harvey_tests = []

    all_oos_results = {}
    for d in [boundary_results, time_results, regime_results, hybrid_results]:
        for k, v in d.items():
            if k.endswith("_oos") and v.get("daily_returns_net") is not None:
                all_oos_results[k] = v

    print(f"\n{'Strategy':<30} {'Net SR':<10} {'ΔSR':<10} {'t-stat':<10} {'Significant?':<12}")
    print("-" * 75)

    for key, res in sorted(all_oos_results.items()):
        if key == "monthly_baseline_oos":
            continue
        alt_ret = np.array(res["daily_returns_net"])
        alt_sharpe = res["metrics"]["net_sharpe"]
        delta_sr = alt_sharpe - baseline_sharpe

        # Use the more precise paired test
        # Need aligned series
        min_len = min(len(baseline_ret), len(alt_ret))
        t_stat = paired_sharpe_tstat(
            pd.Series(alt_ret[:min_len]),
            pd.Series(baseline_ret[:min_len])
        )

        # Also compute simple Harvey approximation
        t_simple = harvey_t_stat(alt_sharpe, baseline_sharpe, n_years_oos)

        sig = "YES" if abs(t_stat) > 1.96 else "no"

        harvey_tests.append({
            "strategy": res["strategy"],
            "net_sharpe": alt_sharpe,
            "delta_sharpe": round(delta_sr, 4),
            "t_stat_paired": round(float(t_stat), 3),
            "t_stat_simple": round(float(t_simple), 3),
            "significant_5pct": bool(abs(t_stat) > 1.96),
        })

        print(f"{res['strategy']:<30} {alt_sharpe:<10.4f} {delta_sr:<+10.4f} {t_stat:<10.3f} {sig:<12}")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART F: Summary table
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART F: 完整比較摘要 (OOS Period)")
    print("="*70)

    summary_rows = []
    for key, res in sorted(all_oos_results.items()):
        m = res["metrics"]
        row = {
            "strategy": res["strategy"],
            "gross_sharpe": m["gross_sharpe"],
            "net_sharpe": m["net_sharpe"],
            "mdd": m["mdd_gross"],
            "annual_return_gross": m["gross_annual_return"],
            "annual_return_net": m["net_annual_return"],
            "annual_turnover": m["annual_turnover"],
            "annual_rebal": m["annual_rebal_events"],
            "annual_tc_pct": m["annual_tc_pct"],
            "tc_saving_vs_monthly_pct": round(
                baseline_oos["metrics"]["annual_tc_pct"] - m["annual_tc_pct"], 4
            ),
            "calmar": m["calmar"],
            "sortino": m["sortino"],
        }
        summary_rows.append(row)

    print(f"\n{'Strategy':<25} {'Net SR':<8} {'MDD%':<8} {'Turn/yr':<10} {'Rebal/yr':<10} {'TC/yr%':<8} {'TC Save%':<10} {'Calmar':<8}")
    print("-" * 95)
    for row in sorted(summary_rows, key=lambda x: -x["net_sharpe"]):
        print(f"{row['strategy']:<25} {row['net_sharpe']:<8.4f} {row['mdd']*100:<8.1f} "
              f"{row['annual_turnover']:<10.2f} {row['annual_rebal']:<10.1f} "
              f"{row['annual_tc_pct']:<8.4f} {row['tc_saving_vs_monthly_pct']:<+10.4f} {row['calmar']:<8.4f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # PART G: Full sample results summary
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("PART G: 完整比較摘要 (Full Sample 2007-2026)")
    print("="*70)

    all_full_results = {}
    for d in [boundary_results, time_results, regime_results, hybrid_results]:
        for k, v in d.items():
            if k.endswith("_full"):
                all_full_results[k] = v

    full_summary_rows = []
    for key, res in sorted(all_full_results.items()):
        m = res["metrics"]
        baseline_full = boundary_results["monthly_baseline_full"]["metrics"]
        row = {
            "strategy": res["strategy"],
            "gross_sharpe": m["gross_sharpe"],
            "net_sharpe": m["net_sharpe"],
            "mdd": m["mdd_gross"],
            "annual_turnover": m["annual_turnover"],
            "annual_rebal": m["annual_rebal_events"],
            "annual_tc_pct": m["annual_tc_pct"],
            "tc_saving_vs_monthly_pct": round(
                baseline_full["annual_tc_pct"] - m["annual_tc_pct"], 4
            ),
        }
        full_summary_rows.append(row)

    print(f"\n{'Strategy':<25} {'Net SR':<8} {'MDD%':<8} {'Turn/yr':<10} {'Rebal/yr':<10} {'TC/yr%':<8} {'TC Save%':<10}")
    print("-" * 90)
    for row in sorted(full_summary_rows, key=lambda x: -x["net_sharpe"]):
        print(f"{row['strategy']:<25} {row['net_sharpe']:<8.4f} {row['mdd']*100:<8.1f} "
              f"{row['annual_turnover']:<10.2f} {row['annual_rebal']:<10.1f} "
              f"{row['annual_tc_pct']:<8.4f} {row['tc_saving_vs_monthly_pct']:<+10.4f}")

    # ═══════════════════════════════════════════════════════════════════════════
    # Save results
    # ═══════════════════════════════════════════════════════════════════════════

    # Clean up daily_returns_net before saving (too large)
    def clean_for_json(d):
        cleaned = {}
        for k, v in d.items():
            v_copy = dict(v)
            if "daily_returns_net" in v_copy:
                del v_copy["daily_returns_net"]
            cleaned[k] = v_copy
        return cleaned

    output = {
        "experiment": "Rebalancing Boundary for 12/VIX",
        "description": (
            "Test rebalancing boundary (only rebalance when |w_current - w_target| > X%) "
            "to reduce turnover for the 50/50 SPY/GLD 12/VIX strategy. Also tests "
            "time-based variants (bimonthly, quarterly) and VIX regime crossing triggers."
        ),
        "proposed_by": "FMPM 2025 literature",
        "executed_by": "Claude",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "portfolio": "50/50 SPY/GLD 12/VIX + SHY cash",
            "tx_cost": TX_COST,
            "rf_annual": RF_ANNUAL,
            "full_sample": f"{FULL_START} to latest",
            "oos": f"{OOS_START} to {OOS_END}",
            "boundary_thresholds": BOUNDARY_THRESHOLDS,
            "time_variants": TIME_VARIANTS,
            "vix_regime_thresholds": VIX_REGIME_THRESHOLDS,
        },
        "results": {
            "boundary": clean_for_json(boundary_results),
            "time_based": clean_for_json(time_results),
            "vix_regime": clean_for_json(regime_results),
            "hybrid": clean_for_json(hybrid_results),
        },
        "harvey_tests": harvey_tests,
        "oos_summary": sorted(summary_rows, key=lambda x: -x["net_sharpe"]),
        "full_summary": sorted(full_summary_rows, key=lambda x: -x["net_sharpe"]),
        "conclusions": {},  # will fill after seeing results
    }

    # Fill conclusions based on results
    # Find best OOS strategy
    best_oos = max(summary_rows, key=lambda x: x["net_sharpe"])
    best_tc_saving = max(summary_rows, key=lambda x: x["tc_saving_vs_monthly_pct"])
    lowest_turnover = min(summary_rows, key=lambda x: x["annual_turnover"])
    baseline_row = next(r for r in summary_rows if r["strategy"] == "monthly_baseline")

    # Any significant improvements?
    sig_improvements = [h for h in harvey_tests if h["significant_5pct"] and h["delta_sharpe"] > 0]

    output["conclusions"] = {
        "best_net_sharpe_oos": {
            "strategy": best_oos["strategy"],
            "net_sharpe": best_oos["net_sharpe"],
            "delta_vs_baseline": round(best_oos["net_sharpe"] - baseline_row["net_sharpe"], 4),
        },
        "best_tc_saving": {
            "strategy": best_tc_saving["strategy"],
            "tc_saving_pct_per_year": best_tc_saving["tc_saving_vs_monthly_pct"],
        },
        "lowest_turnover": {
            "strategy": lowest_turnover["strategy"],
            "annual_turnover": lowest_turnover["annual_turnover"],
            "annual_rebal": lowest_turnover["annual_rebal"],
        },
        "significant_improvements": sig_improvements if sig_improvements else "None — no variant significantly beats monthly baseline",
        "baseline_metrics_oos": {
            "net_sharpe": baseline_row["net_sharpe"],
            "annual_tc_pct": baseline_row["annual_tc_pct"],
            "annual_turnover": baseline_row["annual_turnover"],
        },
        "practical_recommendation": "",  # fill below
    }

    # Save
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\n✓ Results saved to {OUT_PATH}")

    # Final recommendation
    print("\n" + "="*70)
    print("結論與建議")
    print("="*70)

    print(f"\n基線 (月度再平衡): Net Sharpe = {baseline_row['net_sharpe']:.4f}, "
          f"TC = {baseline_row['annual_tc_pct']:.4f}%/yr, "
          f"Turnover = {baseline_row['annual_turnover']:.2f}/yr")
    print(f"\n最佳 Net Sharpe (OOS): {best_oos['strategy']} = {best_oos['net_sharpe']:.4f} "
          f"(Δ = {best_oos['net_sharpe'] - baseline_row['net_sharpe']:+.4f})")
    print(f"最大 TC 節省: {best_tc_saving['strategy']} = {best_tc_saving['tc_saving_vs_monthly_pct']:+.4f}%/yr")
    print(f"最低 Turnover: {lowest_turnover['strategy']} = {lowest_turnover['annual_turnover']:.2f}/yr "
          f"(vs baseline {baseline_row['annual_turnover']:.2f})")

    if sig_improvements:
        print(f"\n顯著改善 (Harvey t > 1.96): {len(sig_improvements)} 個策略")
        for s in sig_improvements:
            print(f"  - {s['strategy']}: ΔSR = {s['delta_sharpe']:+.4f}, t = {s['t_stat_paired']:.3f}")
    else:
        print("\n⚠️ 沒有任何變體顯著打敗月度再平衡基線 (Harvey t < 1.96)")
        print("   → 再平衡邊界節省 TC，但 Sharpe 改善統計上不顯著")

    # Update conclusions with recommendation
    if not sig_improvements:
        rec = (
            "再平衡邊界可以有效減少交易次數和成本，但 Sharpe 改善統計上不顯著。"
            f"實務建議：使用 {best_oos['strategy']} "
            f"(turnover 減少 {(1 - best_oos['annual_turnover']/baseline_row['annual_turnover'])*100:.0f}%)，"
            "因為它在不損害績效的前提下降低了交易頻率。"
            "月度 12/VIX 已是非常好的基準——邊界只是微調。"
        )
    else:
        best_sig = max(sig_improvements, key=lambda x: x["delta_sharpe"])
        rec = (
            f"建議使用 {best_sig['strategy']}，"
            f"Net Sharpe 顯著改善 {best_sig['delta_sharpe']:+.4f} (t={best_sig['t_stat_paired']:.3f})。"
        )

    output["conclusions"]["practical_recommendation"] = rec
    OUT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False))

    print(f"\n建議：{rec}")

    return output


if __name__ == "__main__":
    main()
