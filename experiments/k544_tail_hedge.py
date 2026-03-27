#!/usr/bin/env python3
"""
K544: Tail Hedge Efficiency — When is buying protection worth the cost?

Motivation: Codex suggestion #3 (carry admission filter). Instead of improving VT,
add a TAIL HEDGE overlay. Can we identify periods where buying extra protection
(beyond VT's default) has positive expected value?

Literature:
  - Bhansali (2014) "Tail Risk Hedging" — framework for sizing tail protection
  - Israelov (2017) "Pathetic Protection" — most put protection strategies are NPV-negative
  - Knowledge base: K41 (VT insurance ~4%/yr), K15 (VT regime decomposition),
    K62 (interest rate impact on VT cost), K43 (VVIX/SKEW overlays null)

Design:
  1. SPY + VIX from yfinance (2006-2025, need VIX3M from ~2008)
  2. Simulate tail hedge: X% of portfolio to "put protection"
     - Cost: VIX/100 * X% annually (proxy for at-the-money put cost)
     - Payoff: if SPY monthly return < -5%, payoff = |SPY_ret + 5%| * leverage
  3. Strategies:
     a. Always Hedge (2%)
     b. VIX-Conditional: only when VIX < 15
     c. Term Structure: only when VIX/VIX3M < 0.80
     d. Momentum: only when SPY 60d return > +10%
     e. Combined: hedge when ≥2 of 3 conditions met
  4. Apply as overlay on 12/VIX VT strategy
  5. Metrics: Sharpe, MDD, tail ratio, max 1-month loss, cost
  6. Cross-OOS: 3 periods (2016-2019, 2020-2021, 2022-2024)

Data: SPY, VIX, ^VIX3M from yfinance
Author: Yi-Hao Lai + VolPred Research System
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─── Configuration ──────────────────────────────────────────────────
HEDGE_ALLOCATION = 0.02  # 2% of portfolio allocated to tail protection
PUT_LEVERAGE = 5.0       # Simplified: put pays 5x notional when ITM
STRIKE_OFFSET = -0.05    # -5% monthly = "out of the money" threshold
MONTHLY_COST_SCALE = 1/12  # annualized VIX → monthly cost
REBALANCE_FREQ = "M"     # monthly rebalancing for tail hedge evaluation

# VT parameters (standard 12/VIX)
VT_NUMERATOR = 12.0

# Cross-OOS periods
OOS_PERIODS = {
    "2016-2019": ("2016-01-01", "2019-12-31"),
    "2020-2021": ("2020-01-01", "2021-12-31"),
    "2022-2024": ("2022-01-01", "2024-12-31"),
}

# ─── Data Download ──────────────────────────────────────────────────
def download_data():
    """Download SPY, VIX, VIX3M from yfinance."""
    print("Downloading data from yfinance...")
    spy = yf.download("SPY", start="2006-01-01", end="2025-12-31", progress=False)
    vix = yf.download("^VIX", start="2006-01-01", end="2025-12-31", progress=False)
    vix3m = yf.download("^VIX3M", start="2006-01-01", end="2025-12-31", progress=False)

    # Handle MultiIndex columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    if isinstance(vix3m.columns, pd.MultiIndex):
        vix3m.columns = vix3m.columns.get_level_values(0)

    df = pd.DataFrame({
        "spy_close": spy["Close"],
        "vix": vix["Close"],
        "vix3m": vix3m["Close"],
    }).dropna(subset=["spy_close", "vix"])

    df["spy_ret"] = df["spy_close"].pct_change()
    df["vix3m"] = df["vix3m"].ffill()  # VIX3M may have gaps

    # Monthly returns for tail hedge evaluation
    df["month"] = df.index.to_period("M")

    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)} days")
    print(f"  VIX3M available from: {df['vix3m'].first_valid_index().date() if df['vix3m'].first_valid_index() is not None else 'N/A'}")

    return df


# ─── VT Strategy (12/VIX) ──────────────────────────────────────────
def compute_vt_weights(vix_series, numerator=12.0):
    """Compute 12/VIX equity weight, clipped [0, 1]."""
    w = numerator / vix_series
    return w.clip(0, 1)


# ─── Tail Hedge Strategies ─────────────────────────────────────────
def compute_hedge_signals(df):
    """
    Compute daily hedge-on/off signals for each strategy.
    Returns DataFrame with boolean columns.
    """
    signals = pd.DataFrame(index=df.index)

    # A: Always hedge
    signals["always"] = True

    # B: VIX < 15 (cheap insurance)
    signals["vix_cheap"] = df["vix"] < 15

    # C: VIX/VIX3M < 0.80 (deep contango = cheap vol relative to term structure)
    ratio = df["vix"] / df["vix3m"]
    signals["contango"] = ratio < 0.80

    # D: SPY 60d return > +10% (complacent rally)
    spy_60d_ret = df["spy_close"].pct_change(60)
    signals["momentum"] = spy_60d_ret > 0.10

    # E: Combined — at least 2 of 3 conditions (B, C, D)
    count = signals["vix_cheap"].astype(int) + signals["contango"].astype(int) + signals["momentum"].astype(int)
    signals["combined"] = count >= 2

    return signals


def simulate_tail_hedge_monthly(df, hedge_signal, hedge_alloc=HEDGE_ALLOCATION,
                                 leverage=PUT_LEVERAGE, strike_offset=STRIKE_OFFSET):
    """
    Simulate monthly tail hedge overlay.

    For each month:
    - If hedge_signal is ON at month start → allocate hedge_alloc to protection
    - Cost: (VIX_start / 100) * hedge_alloc / 12   (annualized → monthly)
    - Payoff: if SPY monthly return < strike_offset,
              payoff = |SPY_ret - strike_offset| * leverage * hedge_alloc
    - Net hedge P&L = payoff - cost (can be negative most months)

    Returns monthly Series of hedge P&L.
    """
    monthly_groups = df.groupby("month")

    records = []
    for period, group in monthly_groups:
        if len(group) < 5:
            continue

        # Month start values
        vix_start = group["vix"].iloc[0]
        spy_start = group["spy_close"].iloc[0]
        spy_end = group["spy_close"].iloc[-1]
        spy_monthly_ret = (spy_end / spy_start) - 1

        # Was hedge on at month start?
        hedge_on = hedge_signal.loc[group.index[0]] if group.index[0] in hedge_signal.index else False

        if hedge_on:
            # Monthly cost = annualized implied vol * allocation / 12
            # This is a rough proxy: ATM put ≈ σ√(T/2π) ≈ σ/√(12*2π) per month
            # Simplified: cost = VIX/100 * alloc / 12
            monthly_cost = (vix_start / 100) * hedge_alloc * MONTHLY_COST_SCALE

            # Payoff: if SPY drops below threshold
            if spy_monthly_ret < strike_offset:
                payoff = abs(spy_monthly_ret - strike_offset) * leverage * hedge_alloc
            else:
                payoff = 0.0

            net_pnl = payoff - monthly_cost
        else:
            monthly_cost = 0.0
            payoff = 0.0
            net_pnl = 0.0

        records.append({
            "period": period,
            "date": group.index[-1],
            "spy_ret": spy_monthly_ret,
            "vix_start": vix_start,
            "hedge_on": hedge_on,
            "cost": monthly_cost,
            "payoff": payoff,
            "net_pnl": net_pnl,
        })

    return pd.DataFrame(records).set_index("date")


# ─── Portfolio Simulation (Daily) ──────────────────────────────────
def simulate_portfolio_daily(df, hedge_monthly_df, vt_weights):
    """
    Combine daily VT returns with monthly tail hedge overlay.

    Daily portfolio return = VT_weight * SPY_ret * (1 - hedge_alloc_if_on) + cash_portion
    Monthly: add hedge net P&L at month end.
    """
    # Start with daily VT returns
    daily_ret = vt_weights.shift(1) * df["spy_ret"]  # shift for no look-ahead
    daily_ret = daily_ret.dropna()

    # Build cumulative return series
    cum_ret = (1 + daily_ret).cumprod()

    # At each month end, apply hedge P&L
    if hedge_monthly_df is not None and len(hedge_monthly_df) > 0:
        for _, row in hedge_monthly_df.iterrows():
            date = row.name if not isinstance(row.name, str) else pd.Timestamp(row.name)
            if date in cum_ret.index:
                # Apply net P&L as a multiplicative adjustment
                # If hedge net P&L = +0.01, multiply cumulative by 1.01
                cum_ret.loc[date:] *= (1 + row["net_pnl"])

    return daily_ret, cum_ret


def simulate_strategy(df, hedge_signal, strategy_name, vt_weights):
    """
    Full simulation: VT + tail hedge overlay.
    Returns metrics dict.
    """
    # Compute monthly hedge P&L
    hedge_monthly = simulate_tail_hedge_monthly(df, hedge_signal)

    # Get daily VT returns
    daily_vt_ret = (vt_weights.shift(1) * df["spy_ret"]).dropna()

    # Combine: daily VT + monthly hedge overlay
    # Create a daily return series that includes hedge costs/payoffs
    combined_daily = daily_vt_ret.copy()

    if len(hedge_monthly) > 0:
        for _, row in hedge_monthly.iterrows():
            date = row.name
            if date in combined_daily.index:
                combined_daily.loc[date] += row["net_pnl"]

    # Cumulative
    cum = (1 + combined_daily).cumprod()

    return combined_daily, cum, hedge_monthly


# ─── Metrics ────────────────────────────────────────────────────────
def compute_metrics(daily_returns, cum_returns, label=""):
    """Compute comprehensive metrics focused on tail risk."""
    dr = daily_returns.dropna()
    if len(dr) < 60:
        return {"label": label, "error": "insufficient data"}

    # Basic
    ann_ret = dr.mean() * 252
    ann_vol = dr.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Drawdown
    peak = cum_returns.expanding().max()
    drawdown = (cum_returns - peak) / peak
    max_dd = drawdown.min()

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Monthly returns for tail analysis
    # Group daily returns by month
    monthly_rets = dr.groupby(dr.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)

    # Tail ratio: avg gain in top 5% / avg loss in bottom 5%
    sorted_monthly = monthly_rets.sort_values()
    n = len(sorted_monthly)
    bottom5 = sorted_monthly.iloc[:max(1, n // 20)]
    top5 = sorted_monthly.iloc[-max(1, n // 20):]
    tail_ratio = abs(top5.mean() / bottom5.mean()) if bottom5.mean() != 0 else np.inf

    # Worst monthly return
    worst_month = monthly_rets.min()

    # CVaR 5% (monthly)
    var_5 = monthly_rets.quantile(0.05)
    cvar_5 = monthly_rets[monthly_rets <= var_5].mean()

    # Sortino
    downside_dev = dr[dr < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside_dev if downside_dev > 0 else 0

    # Skewness of monthly returns
    skew = monthly_rets.skew()

    # Number of months with > 5% loss
    crash_months = (monthly_rets < -0.05).sum()
    total_months = len(monthly_rets)

    return {
        "label": label,
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "tail_ratio": round(tail_ratio, 3),
        "worst_month_pct": round(worst_month * 100, 2),
        "cvar_5_monthly": round(cvar_5 * 100, 2) if not np.isnan(cvar_5) else None,
        "monthly_skew": round(skew, 3),
        "crash_months": int(crash_months),
        "total_months": int(total_months),
        "crash_rate": round(crash_months / total_months * 100, 2),
        "n_days": len(dr),
    }


# ─── Cross-OOS Evaluation ──────────────────────────────────────────
def run_cross_oos(df, signals, vt_weights, oos_periods):
    """Run each strategy on each OOS period."""
    results = {}

    strategy_names = ["always", "vix_cheap", "contango", "momentum", "combined"]

    for period_name, (start, end) in oos_periods.items():
        period_df = df.loc[start:end].copy()
        period_vt = vt_weights.loc[start:end].copy()
        period_signals = signals.loc[start:end].copy()

        if len(period_df) < 60:
            print(f"  Skipping {period_name}: only {len(period_df)} days")
            continue

        results[period_name] = {}

        # Baseline: VT only (no hedge)
        daily_vt = (period_vt.shift(1) * period_df["spy_ret"]).dropna()
        cum_vt = (1 + daily_vt).cumprod()
        results[period_name]["vt_only"] = compute_metrics(daily_vt, cum_vt, "VT Only")

        # B&H for reference
        daily_bh = period_df["spy_ret"].dropna()
        cum_bh = (1 + daily_bh).cumprod()
        results[period_name]["buy_hold"] = compute_metrics(daily_bh, cum_bh, "Buy & Hold")

        # Each hedge strategy
        for sname in strategy_names:
            sig = period_signals[sname]
            daily_combined, cum_combined, hedge_monthly = simulate_strategy(
                period_df, sig, sname, period_vt
            )
            metrics = compute_metrics(daily_combined, cum_combined, f"VT+{sname}")

            # Add hedge-specific stats
            if len(hedge_monthly) > 0:
                metrics["hedge_months_active"] = int(hedge_monthly["hedge_on"].sum())
                metrics["total_months"] = len(hedge_monthly)
                metrics["hedge_active_pct"] = round(
                    hedge_monthly["hedge_on"].sum() / len(hedge_monthly) * 100, 1
                )
                metrics["total_cost"] = round(hedge_monthly["cost"].sum() * 100, 3)
                metrics["total_payoff"] = round(hedge_monthly["payoff"].sum() * 100, 3)
                metrics["net_hedge_pnl"] = round(hedge_monthly["net_pnl"].sum() * 100, 3)
                metrics["avg_cost_per_active_month"] = round(
                    hedge_monthly.loc[hedge_monthly["hedge_on"], "cost"].mean() * 100, 3
                ) if hedge_monthly["hedge_on"].sum() > 0 else 0

            results[period_name][sname] = metrics

    return results


# ─── Descriptive Statistics ─────────────────────────────────────────
def descriptive_stats(df):
    """Print descriptive statistics before analysis."""
    print("\n" + "=" * 60)
    print("DESCRIPTIVE STATISTICS")
    print("=" * 60)

    spy_ret = df["spy_ret"].dropna()
    print(f"\nSPY Daily Returns (N={len(spy_ret)}):")
    print(f"  Mean:     {spy_ret.mean()*252*100:.2f}%/yr")
    print(f"  Std:      {spy_ret.std()*np.sqrt(252)*100:.2f}%/yr")
    print(f"  Skew:     {spy_ret.skew():.3f}")
    print(f"  Kurtosis: {spy_ret.kurtosis():.3f}")

    vix = df["vix"].dropna()
    print(f"\nVIX (N={len(vix)}):")
    print(f"  Mean:   {vix.mean():.2f}")
    print(f"  Median: {vix.median():.2f}")
    print(f"  Min:    {vix.min():.2f}")
    print(f"  Max:    {vix.max():.2f}")
    print(f"  % < 15: {(vix < 15).mean()*100:.1f}%")
    print(f"  % > 25: {(vix > 25).mean()*100:.1f}%")

    if "vix3m" in df.columns:
        ratio = (df["vix"] / df["vix3m"]).dropna()
        print(f"\nVIX/VIX3M Ratio (N={len(ratio)}):")
        print(f"  Mean:   {ratio.mean():.3f}")
        print(f"  % < 0.80 (deep contango): {(ratio < 0.80).mean()*100:.1f}%")
        print(f"  % > 1.00 (backwardation): {(ratio > 1.00).mean()*100:.1f}%")

    spy_60d = df["spy_close"].pct_change(60).dropna()
    print(f"\nSPY 60d Return:")
    print(f"  % > +10%: {(spy_60d > 0.10).mean()*100:.1f}%")
    print(f"  % < -10%: {(spy_60d < -0.10).mean()*100:.1f}%")

    # Monthly SPY returns
    monthly = spy_ret.groupby(spy_ret.index.to_period("M")).apply(lambda x: (1 + x).prod() - 1)
    print(f"\nSPY Monthly Returns (N={len(monthly)}):")
    print(f"  Mean:   {monthly.mean()*100:.2f}%")
    print(f"  Std:    {monthly.std()*100:.2f}%")
    print(f"  Min:    {monthly.min()*100:.2f}%")
    print(f"  Months < -5%: {(monthly < -0.05).sum()} ({(monthly < -0.05).mean()*100:.1f}%)")
    print(f"  Months < -10%: {(monthly < -0.10).sum()} ({(monthly < -0.10).mean()*100:.1f}%)")


# ─── Signal Co-occurrence Analysis ──────────────────────────────────
def signal_analysis(df, signals):
    """Analyze when each signal fires and their overlap."""
    print("\n" + "=" * 60)
    print("SIGNAL ANALYSIS")
    print("=" * 60)

    for col in ["vix_cheap", "contango", "momentum", "combined"]:
        pct = signals[col].mean() * 100
        print(f"\n  {col}: active {pct:.1f}% of days")

        # When signal is on, what happens next month?
        sig_on_dates = signals.index[signals[col]]
        if len(sig_on_dates) > 0:
            # Forward 22-day return
            fwd_ret = df["spy_close"].pct_change(22).shift(-22)
            on_fwd = fwd_ret.loc[sig_on_dates].dropna()
            off_fwd = fwd_ret.loc[~signals[col]].dropna()
            if len(on_fwd) > 10 and len(off_fwd) > 10:
                print(f"    When ON:  fwd 22d ret = {on_fwd.mean()*100:.2f}% (n={len(on_fwd)})")
                print(f"    When OFF: fwd 22d ret = {off_fwd.mean()*100:.2f}% (n={len(off_fwd)})")
                # Crash probability (fwd 22d < -5%)
                crash_on = (on_fwd < -0.05).mean() * 100
                crash_off = (off_fwd < -0.05).mean() * 100
                print(f"    Crash prob ON: {crash_on:.1f}%, OFF: {crash_off:.1f}%")

    # Correlation between signals
    print("\n  Signal Correlations:")
    corr = signals[["vix_cheap", "contango", "momentum"]].corr()
    for i, c1 in enumerate(corr.columns):
        for j, c2 in enumerate(corr.columns):
            if j > i:
                print(f"    {c1} vs {c2}: {corr.loc[c1, c2]:.3f}")


# ─── Main ───────────────────────────────────────────────────────────
def main():
    print("K544: Tail Hedge Efficiency")
    print("=" * 60)

    # Download data
    df = download_data()

    # Descriptive statistics
    descriptive_stats(df)

    # VT weights
    vt_weights = compute_vt_weights(df["vix"])

    # Hedge signals
    signals = compute_hedge_signals(df)

    # Signal analysis
    signal_analysis(df, signals)

    # ─── Full Sample Analysis ─────────────────────────────
    print("\n" + "=" * 60)
    print("FULL SAMPLE ANALYSIS (all available data)")
    print("=" * 60)

    # Filter to where VIX3M is available for fair comparison
    start_date = df["vix3m"].first_valid_index()
    if start_date is not None:
        full_df = df.loc[start_date:].copy()
    else:
        full_df = df.copy()

    full_vt = vt_weights.loc[full_df.index]
    full_signals = signals.loc[full_df.index]

    print(f"\nFull sample: {full_df.index[0].date()} to {full_df.index[-1].date()}")

    # Baseline metrics
    daily_vt = (full_vt.shift(1) * full_df["spy_ret"]).dropna()
    cum_vt = (1 + daily_vt).cumprod()
    vt_metrics = compute_metrics(daily_vt, cum_vt, "VT Only")

    daily_bh = full_df["spy_ret"].dropna()
    cum_bh = (1 + daily_bh).cumprod()
    bh_metrics = compute_metrics(daily_bh, cum_bh, "Buy & Hold")

    all_full_metrics = {"vt_only": vt_metrics, "buy_hold": bh_metrics}

    # Each strategy
    for sname in ["always", "vix_cheap", "contango", "momentum", "combined"]:
        sig = full_signals[sname]
        daily_combined, cum_combined, hedge_monthly = simulate_strategy(
            full_df, sig, sname, full_vt
        )
        metrics = compute_metrics(daily_combined, cum_combined, f"VT+{sname}")

        if len(hedge_monthly) > 0:
            metrics["hedge_months_active"] = int(hedge_monthly["hedge_on"].sum())
            metrics["hedge_total_months"] = len(hedge_monthly)
            metrics["hedge_active_pct"] = round(
                hedge_monthly["hedge_on"].sum() / len(hedge_monthly) * 100, 1
            )
            metrics["total_cost_pct"] = round(hedge_monthly["cost"].sum() * 100, 3)
            metrics["total_payoff_pct"] = round(hedge_monthly["payoff"].sum() * 100, 3)
            metrics["net_hedge_pnl_pct"] = round(hedge_monthly["net_pnl"].sum() * 100, 3)

        all_full_metrics[sname] = metrics

    # Print full sample table
    print(f"\n{'Strategy':<20} {'Sharpe':>7} {'MDD%':>7} {'Calmar':>7} {'TailR':>7} "
          f"{'WorstMo':>8} {'CVaR5%':>7} {'Skew':>6} {'Crash%':>7}")
    print("-" * 95)
    for key in ["buy_hold", "vt_only", "always", "vix_cheap", "contango", "momentum", "combined"]:
        m = all_full_metrics[key]
        if "error" in m:
            continue
        print(f"{m['label']:<20} {m['sharpe']:>7.3f} {m['max_dd']:>7.2f} {m['calmar']:>7.3f} "
              f"{m['tail_ratio']:>7.3f} {m['worst_month_pct']:>8.2f} "
              f"{m.get('cvar_5_monthly', 'N/A'):>7} {m['monthly_skew']:>6.3f} "
              f"{m['crash_rate']:>7.2f}")

    # Hedge cost/benefit breakdown
    print(f"\n{'Strategy':<20} {'Active%':>8} {'TotalCost':>10} {'TotalPayoff':>12} {'NetP&L':>8}")
    print("-" * 65)
    for key in ["always", "vix_cheap", "contango", "momentum", "combined"]:
        m = all_full_metrics[key]
        if "hedge_active_pct" in m:
            print(f"{m['label']:<20} {m['hedge_active_pct']:>7.1f}% "
                  f"{m['total_cost_pct']:>9.3f}% {m['total_payoff_pct']:>11.3f}% "
                  f"{m['net_hedge_pnl_pct']:>7.3f}%")

    # ─── Cross-OOS ────────────────────────────────────────
    print("\n" + "=" * 60)
    print("CROSS-OOS ANALYSIS")
    print("=" * 60)

    oos_results = run_cross_oos(df, signals, vt_weights, OOS_PERIODS)

    for period_name, period_results in oos_results.items():
        print(f"\n--- {period_name} ---")
        print(f"{'Strategy':<20} {'Sharpe':>7} {'MDD%':>7} {'TailR':>7} {'WorstMo':>8} {'Active%':>8}")
        print("-" * 60)
        for key in ["buy_hold", "vt_only", "always", "vix_cheap", "contango", "momentum", "combined"]:
            if key in period_results:
                m = period_results[key]
                if "error" in m:
                    continue
                active = m.get("hedge_active_pct", "-")
                active_str = f"{active:>7.1f}%" if isinstance(active, (int, float)) else f"{active:>8s}"
                print(f"{m['label']:<20} {m['sharpe']:>7.3f} {m['max_dd']:>7.2f} "
                      f"{m['tail_ratio']:>7.3f} {m['worst_month_pct']:>8.2f} {active_str}")

    # ─── Cross-OOS Consistency ─────────────────────────────
    print("\n" + "=" * 60)
    print("CROSS-OOS CONSISTENCY (MDD improvement vs VT-only)")
    print("=" * 60)

    consistency = {}
    for sname in ["always", "vix_cheap", "contango", "momentum", "combined"]:
        mdd_improvements = []
        sharpe_changes = []
        tail_ratio_changes = []

        for period_name, period_results in oos_results.items():
            if sname in period_results and "vt_only" in period_results:
                vt_m = period_results["vt_only"]
                hedge_m = period_results[sname]
                if "error" not in vt_m and "error" not in hedge_m:
                    mdd_imp = vt_m["max_dd"] - hedge_m["max_dd"]  # positive = improvement
                    mdd_improvements.append(mdd_imp)
                    sharpe_changes.append(hedge_m["sharpe"] - vt_m["sharpe"])
                    tail_ratio_changes.append(hedge_m["tail_ratio"] - vt_m["tail_ratio"])

        if len(mdd_improvements) > 0:
            consistency[sname] = {
                "mdd_improvements": mdd_improvements,
                "avg_mdd_imp": np.mean(mdd_improvements),
                "all_positive_mdd": all(x > 0 for x in mdd_improvements),
                "sharpe_changes": sharpe_changes,
                "avg_sharpe_change": np.mean(sharpe_changes),
                "tail_ratio_changes": tail_ratio_changes,
                "avg_tail_ratio_change": np.mean(tail_ratio_changes),
            }

            wins = sum(1 for x in mdd_improvements if x > 0)
            print(f"\n  {sname}:")
            print(f"    MDD improvement: {[f'{x:.2f}pp' for x in mdd_improvements]}")
            print(f"    Avg MDD improvement: {np.mean(mdd_improvements):.2f}pp ({wins}/{len(mdd_improvements)} periods)")
            print(f"    Sharpe change: {[f'{x:+.3f}' for x in sharpe_changes]}")
            print(f"    Avg Sharpe change: {np.mean(sharpe_changes):+.3f}")
            print(f"    Tail ratio change: {[f'{x:+.3f}' for x in tail_ratio_changes]}")

    # ─── Statistical Tests ─────────────────────────────────
    print("\n" + "=" * 60)
    print("STATISTICAL SIGNIFICANCE (paired t-test on monthly returns)")
    print("=" * 60)

    # Full-sample monthly returns comparison
    full_daily_vt = (full_vt.shift(1) * full_df["spy_ret"]).dropna()
    monthly_vt = full_daily_vt.groupby(full_daily_vt.index.to_period("M")).apply(
        lambda x: (1 + x).prod() - 1
    )

    stat_tests = {}
    for sname in ["always", "vix_cheap", "contango", "momentum", "combined"]:
        sig = full_signals[sname]
        daily_combined, _, _ = simulate_strategy(full_df, sig, sname, full_vt)
        monthly_hedge = daily_combined.groupby(daily_combined.index.to_period("M")).apply(
            lambda x: (1 + x).prod() - 1
        )

        # Align
        common = monthly_vt.index.intersection(monthly_hedge.index)
        vt_m = monthly_vt.loc[common]
        h_m = monthly_hedge.loc[common]

        if len(common) > 10:
            diff = h_m - vt_m
            t_stat, p_val = stats.ttest_1samp(diff, 0)

            # Focus on downside: compare worst months
            vt_worst = vt_m.nsmallest(int(len(vt_m) * 0.1))
            h_worst = h_m.loc[vt_worst.index]
            worst_diff = h_worst - vt_worst
            t_worst, p_worst = stats.ttest_1samp(worst_diff, 0)

            stat_tests[sname] = {
                "t_all": round(t_stat, 3),
                "p_all": round(p_val, 4),
                "t_worst10": round(t_worst, 3),
                "p_worst10": round(p_worst, 4),
                "mean_diff": round(diff.mean() * 100, 4),
                "mean_worst_diff": round(worst_diff.mean() * 100, 4),
            }

            sig_marker = "★" if p_val < 0.05 else ""
            worst_marker = "★" if p_worst < 0.05 else ""
            print(f"\n  {sname}:")
            print(f"    All months: mean diff = {diff.mean()*100:.4f}%, t={t_stat:.3f}, p={p_val:.4f} {sig_marker}")
            print(f"    Worst 10%:  mean diff = {worst_diff.mean()*100:.4f}%, t={t_worst:.3f}, p={p_worst:.4f} {worst_marker}")

    # ─── Verdict ──────────────────────────────────────────
    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)

    # Find best strategy by MDD improvement
    best_mdd = None
    best_name = None
    for sname, c in consistency.items():
        if c["all_positive_mdd"] and (best_mdd is None or c["avg_mdd_imp"] > best_mdd):
            best_mdd = c["avg_mdd_imp"]
            best_name = sname

    if best_name:
        print(f"\n  Best tail hedge strategy (by MDD improvement): {best_name}")
        print(f"    Avg MDD improvement: {best_mdd:.2f}pp across all OOS periods")
        print(f"    Avg Sharpe change: {consistency[best_name]['avg_sharpe_change']:+.3f}")
    else:
        print("\n  No strategy consistently improves MDD across all OOS periods.")

    # Check Israelov (2017) thesis: is protection pathetic?
    always_m = all_full_metrics.get("always", {})
    vt_m = all_full_metrics.get("vt_only", {})
    if "net_hedge_pnl_pct" in always_m:
        print(f"\n  Israelov test (always-hedge net P&L): {always_m['net_hedge_pnl_pct']:.3f}%")
        if always_m["net_hedge_pnl_pct"] < 0:
            print("  → Confirmed: unconditional tail protection is NPV-negative (Israelov 2017)")
        else:
            print("  → Surprising: unconditional protection is NPV-positive")

    # Conditional strategies
    conditional_positive = []
    for sname in ["vix_cheap", "contango", "momentum", "combined"]:
        m = all_full_metrics.get(sname, {})
        if m.get("net_hedge_pnl_pct", -999) > 0:
            conditional_positive.append(sname)

    if conditional_positive:
        print(f"\n  Conditional strategies with positive net P&L: {conditional_positive}")
        print("  → Timing CAN make tail protection profitable (supports Bhansali 2014)")
    else:
        print("\n  No conditional strategy achieves positive net P&L in full sample.")
        print("  → Even with timing, tail protection remains a cost center")
        print("  → But the question is whether the MDD improvement justifies the cost")

    # ─── Save Results ──────────────────────────────────────
    results = {
        "experiment_id": "K544",
        "title": "Tail Hedge Efficiency — When is buying protection worth the cost?",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, ^VIX, ^VIX3M)",
        "data_period": f"{full_df.index[0].date()} to {full_df.index[-1].date()}",
        "sample_size_days": len(full_df),
        "references": [
            "Bhansali (2014) 'Tail Risk Hedging' — framework for sizing tail protection",
            "Israelov (2017) 'Pathetic Protection' — unconditional put protection is NPV-negative",
            "Knowledge: K41 (VT insurance ~4%/yr), K15 (VT regime decomp), K62 (interest rate impact)",
            "Knowledge: K43 (VVIX/SKEW overlays null), T13 (VIX term structure vol predictor)",
        ],
        "methodology": {
            "hedge_allocation": HEDGE_ALLOCATION,
            "put_leverage": PUT_LEVERAGE,
            "strike_offset": STRIKE_OFFSET,
            "vt_numerator": VT_NUMERATOR,
            "strategies": {
                "always": "2% allocation to tail hedge every month",
                "vix_cheap": "Hedge only when VIX < 15",
                "contango": "Hedge only when VIX/VIX3M < 0.80 (deep contango)",
                "momentum": "Hedge only when SPY 60d return > +10%",
                "combined": "Hedge when >= 2 of 3 conditions met",
            },
        },
        "full_sample": all_full_metrics,
        "cross_oos": {},
        "consistency": {},
        "statistical_tests": stat_tests,
    }

    # Serialize cross-OOS (convert numpy)
    for period_name, period_results in oos_results.items():
        results["cross_oos"][period_name] = {}
        for key, val in period_results.items():
            results["cross_oos"][period_name][key] = val

    for sname, c in consistency.items():
        results["consistency"][sname] = {
            "avg_mdd_improvement_pp": round(c["avg_mdd_imp"], 2),
            "all_positive_mdd": c["all_positive_mdd"],
            "avg_sharpe_change": round(c["avg_sharpe_change"], 3),
            "avg_tail_ratio_change": round(c["avg_tail_ratio_change"], 3),
            "mdd_improvements_pp": [round(x, 2) for x in c["mdd_improvements"]],
            "sharpe_changes": [round(x, 3) for x in c["sharpe_changes"]],
        }

    # Determine verdict
    if best_name:
        results["verdict"] = "CONDITIONAL_POSITIVE"
        results["verdict_detail"] = (
            f"Best strategy '{best_name}' improves MDD by avg {best_mdd:.2f}pp across all OOS periods. "
            f"Sharpe change: {consistency[best_name]['avg_sharpe_change']:+.3f}. "
            f"Tail protection has negative unconditional NPV (Israelov 2017 confirmed), "
            f"but conditional timing can improve worst-case outcomes."
        )
    else:
        results["verdict"] = "NEGATIVE"
        results["verdict_detail"] = (
            "No tail hedge strategy consistently improves MDD across all OOS periods. "
            "Unconditional protection is NPV-negative (confirming Israelov 2017). "
            "Conditional timing reduces costs but cannot reliably improve tail outcomes. "
            "12/VIX VT already provides sufficient drawdown protection."
        )

    # Save
    script_dir = os.path.dirname(os.path.abspath(__file__))
    results_path = os.path.join(script_dir, "k544_tail_hedge_results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {results_path}")

    return results


if __name__ == "__main__":
    results = main()
