"""
K273: Crash Taxonomy — Are All Crashes the Same for 50/50+VT?
=============================================================
Background:
  - K269 showed demand shocks (GFC/COVID) vs rate-hike shocks (2022) have different
    correlation dynamics.
  - K271 showed GLD self-heals.
  - Question: Do ALL crash types benefit equally from 50/50+VT?

Methodology:
  1. Identify all SPY drawdowns > 10% (major crashes) from 2005-2024.
     - Start, trough, recovery dates
     - Max drawdown depth
     - Duration (weeks to trough, weeks to recovery)
     - VIX peak during crash
  2. Classify each crash:
     - Type A: Demand shock (VIX spikes >40, GLD positive) — e.g., GFC, COVID
     - Type B: Rate/inflation shock (VIX moderate 20-35, GLD negative) — e.g., 2022
     - Type C: Correction (VIX mild 15-25, quick recovery <8 weeks) — e.g., 2015, 2018
     - Type D: Liquidity crisis (VIX extreme >50, everything sells) — e.g., COVID March
  3. For each crash, measure:
     - 50/50+VT drawdown vs SPY drawdown
     - Protection ratio: (SPY DD - 50/50+VT DD) / SPY DD
     - VT contribution: how much did VT add beyond just 50/50?
  4. Does 50/50+VT work for ALL crash types?

Data: SPY, GLD, ^VIX daily from yfinance. 2005-2024. Real data only.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
VT_THRESHOLD = 12.0  # 12/VIX rule
MAX_WEIGHT = 1.0
MIN_WEIGHT = 0.0

DATA_START = "2004-01-01"  # enough lookback
DATA_END = "2024-12-31"

DRAWDOWN_THRESHOLD = -0.10  # 10% drawdown = major crash


# ==================================================================
# DATA DOWNLOAD
# ==================================================================
def download_data():
    """Download SPY, GLD, VIX daily data from yfinance."""
    print("=" * 70)
    print("K273: Crash Taxonomy — Are All Crashes the Same for 50/50+VT?")
    print("=" * 70)
    print(f"\nDownloading data {DATA_START} to {DATA_END}...")

    spy = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False)
    gld = yf.download("GLD", start=DATA_START, end=DATA_END, progress=False)
    vix = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)

    # Handle multi-level columns from yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Align all on common dates
    prices = pd.DataFrame({
        "SPY": spy["Close"],
        "GLD": gld["Close"],
        "VIX": vix["Close"],
    }).dropna()

    # Flatten any remaining multi-index issues
    prices.index = pd.DatetimeIndex(prices.index)
    for col in prices.columns:
        prices[col] = prices[col].values.flatten()

    print(f"  Data range: {prices.index[0].date()} to {prices.index[-1].date()}")
    print(f"  Trading days: {len(prices)}")

    return prices


# ==================================================================
# DRAWDOWN IDENTIFICATION
# ==================================================================
def find_drawdowns(prices_series, threshold=-0.10):
    """
    Find all drawdown episodes exceeding the threshold.
    Returns list of dicts with start, trough, recovery dates and depths.
    """
    prices = prices_series.values
    dates = prices_series.index

    # Running max
    running_max = np.maximum.accumulate(prices)
    drawdown = prices / running_max - 1

    episodes = []
    i = 0
    n = len(prices)

    while i < n:
        # Find start of drawdown (first time it goes below 0)
        if drawdown[i] < -0.02:  # 2% threshold to start tracking
            start_idx = i
            # Walk back to find the peak
            peak_idx = np.argmax(prices[:i+1])

            # Find the trough
            trough_idx = start_idx
            j = start_idx
            while j < n:
                if drawdown[j] < drawdown[trough_idx]:
                    trough_idx = j
                # Recovery: price returns to peak level
                if prices[j] >= running_max[peak_idx]:
                    recovery_idx = j
                    break
                j += 1
            else:
                recovery_idx = n - 1  # No recovery by end of data

            max_dd = drawdown[trough_idx]

            if max_dd < threshold:
                episodes.append({
                    "peak_date": dates[peak_idx],
                    "trough_date": dates[trough_idx],
                    "recovery_date": dates[recovery_idx] if prices[recovery_idx] >= running_max[peak_idx] else None,
                    "max_dd": float(max_dd),
                    "peak_price": float(prices[peak_idx]),
                    "trough_price": float(prices[trough_idx]),
                    "weeks_to_trough": (dates[trough_idx] - dates[peak_idx]).days / 7,
                    "weeks_to_recovery": (dates[recovery_idx] - dates[peak_idx]).days / 7 if prices[recovery_idx] >= running_max[peak_idx] else None,
                })

                # Skip past recovery to avoid double-counting
                i = recovery_idx + 1 if recovery_idx < n - 1 else n
                continue

        i += 1

    return episodes


# ==================================================================
# CRASH CLASSIFICATION
# ==================================================================
def classify_crash(episode, prices_df):
    """
    Classify a crash episode into Type A/B/C/D.

    Type A: Demand shock (VIX >40, GLD positive)
    Type B: Rate/inflation shock (VIX 20-35, GLD negative)
    Type C: Correction (VIX <30, quick recovery <12 weeks to trough)
    Type D: Liquidity crisis (VIX >50, GLD also negative during peak stress)
    """
    peak = episode["peak_date"]
    trough = episode["trough_date"]

    mask = (prices_df.index >= peak) & (prices_df.index <= trough)
    crash_data = prices_df.loc[mask]

    if len(crash_data) < 2:
        return "C", {"vix_peak": 0, "gld_return": 0}

    vix_peak = float(crash_data["VIX"].max())
    gld_return = float(crash_data["GLD"].iloc[-1] / crash_data["GLD"].iloc[0] - 1)

    # Also check GLD in the most extreme week (around VIX peak)
    vix_peak_date = crash_data["VIX"].idxmax()
    # 5 trading days around VIX peak
    vix_peak_loc = crash_data.index.get_loc(vix_peak_date)
    start_loc = max(0, vix_peak_loc - 5)
    end_loc = min(len(crash_data) - 1, vix_peak_loc + 5)
    gld_around_peak = float(
        crash_data["GLD"].iloc[end_loc] / crash_data["GLD"].iloc[start_loc] - 1
    )

    weeks_to_trough = episode["weeks_to_trough"]

    info = {
        "vix_peak": vix_peak,
        "gld_return": gld_return,
        "gld_around_vix_peak": gld_around_peak,
        "weeks_to_trough": weeks_to_trough,
    }

    # Classification logic
    if vix_peak > 50 and gld_around_peak < -0.03:
        crash_type = "D"  # Liquidity crisis — everything sells
    elif vix_peak > 40 and gld_return > 0:
        crash_type = "A"  # Demand shock — flight to safety
    elif vix_peak > 40 and gld_return < 0:
        # VIX very high but GLD negative — could be D or mixed
        crash_type = "D"  # Liquidity-like
    elif vix_peak < 30 and weeks_to_trough < 12:
        crash_type = "C"  # Mild correction
    elif gld_return < -0.05:
        crash_type = "B"  # Rate/inflation shock
    elif vix_peak < 35:
        crash_type = "C"  # Moderate correction
    else:
        crash_type = "A"  # Default high-VIX

    return crash_type, info


# ==================================================================
# STRATEGY CONSTRUCTION
# ==================================================================
def build_strategies(prices_df):
    """
    Build three strategies:
    1. SPY buy-and-hold
    2. 50/50 SPY/GLD (monthly rebalance)
    3. 50/50 SPY/GLD + 12/VIX (VT overlay, monthly rebalance)

    Returns daily portfolio values.
    """
    spy_ret = prices_df["SPY"].pct_change()
    gld_ret = prices_df["GLD"].pct_change()
    vix = prices_df["VIX"]

    n = len(prices_df)
    dates = prices_df.index

    # Strategy 1: SPY buy-and-hold
    spy_bh = (1 + spy_ret).cumprod()
    spy_bh.iloc[0] = 1.0

    # Strategy 2: 50/50 SPY/GLD (monthly rebalance)
    # Strategy 3: 50/50 + 12/VIX

    nav_5050 = np.ones(n)
    nav_5050vt = np.ones(n)

    w_spy = 0.5
    w_gld = 0.5
    last_rebal_month = dates[0].month

    for i in range(1, n):
        r_spy = spy_ret.iloc[i] if not np.isnan(spy_ret.iloc[i]) else 0
        r_gld = gld_ret.iloc[i] if not np.isnan(gld_ret.iloc[i]) else 0

        # Monthly rebalance check
        current_month = dates[i].month
        if current_month != last_rebal_month:
            w_spy = 0.5
            w_gld = 0.5
            last_rebal_month = current_month

        # 50/50 return
        ret_5050 = w_spy * r_spy + w_gld * r_gld
        nav_5050[i] = nav_5050[i - 1] * (1 + ret_5050)

        # VT weight: 12/VIX, lagged (use previous day's VIX)
        prev_vix = vix.iloc[i - 1]
        vt_weight = np.clip(VT_THRESHOLD / prev_vix, MIN_WEIGHT, MAX_WEIGHT)

        # 50/50+VT: scale portfolio exposure by VT weight, rest in cash
        ret_5050vt = vt_weight * ret_5050
        nav_5050vt[i] = nav_5050vt[i - 1] * (1 + ret_5050vt)

        # Drift weights for 50/50 (between rebalance dates)
        total = w_spy * (1 + r_spy) + w_gld * (1 + r_gld)
        w_spy = w_spy * (1 + r_spy) / total
        w_gld = w_gld * (1 + r_gld) / total

    results = pd.DataFrame({
        "SPY": spy_bh.values,
        "5050": nav_5050,
        "5050_VT": nav_5050vt,
    }, index=dates)

    return results


# ==================================================================
# DRAWDOWN MEASUREMENT FOR EACH STRATEGY
# ==================================================================
def measure_drawdown_in_period(nav_series, start_date, end_date):
    """
    Measure the max drawdown of a strategy during a specific period.
    Uses the strategy's own running max (from the period start).
    """
    mask = (nav_series.index >= start_date) & (nav_series.index <= end_date)
    subset = nav_series.loc[mask]

    if len(subset) < 2:
        return 0.0

    running_max = np.maximum.accumulate(subset.values)
    drawdown = subset.values / running_max - 1
    return float(np.min(drawdown))


def measure_crash_performance(nav_df, episode, extend_weeks=4):
    """
    Measure all strategies' performance during a crash episode.
    Extends slightly beyond trough to capture VT recovery benefit.
    """
    peak = episode["peak_date"]
    trough = episode["trough_date"]

    # Extend end date by extend_weeks beyond trough
    end_date = trough + pd.Timedelta(weeks=extend_weeks)
    if episode["recovery_date"] is not None:
        end_date = min(end_date, episode["recovery_date"])
    end_date = min(end_date, nav_df.index[-1])

    results = {}
    for col in nav_df.columns:
        dd = measure_drawdown_in_period(nav_df[col], peak, trough)
        results[f"{col}_dd"] = dd

    # Protection ratio: (SPY_DD - strategy_DD) / SPY_DD
    spy_dd = results["SPY_dd"]
    if spy_dd < -0.001:
        results["5050_protection"] = (spy_dd - results["5050_dd"]) / spy_dd
        results["5050_VT_protection"] = (spy_dd - results["5050_VT_dd"]) / spy_dd
        results["VT_incremental"] = results["5050_VT_protection"] - results["5050_protection"]
    else:
        results["5050_protection"] = 0
        results["5050_VT_protection"] = 0
        results["VT_incremental"] = 0

    # Recovery speed: days to recover from trough
    for col in nav_df.columns:
        mask = nav_df.index >= trough
        subset = nav_df.loc[mask, col]
        trough_val = subset.iloc[0]
        peak_val = nav_df.loc[nav_df.index <= peak, col].max()
        recovered = subset[subset >= peak_val]
        if len(recovered) > 0:
            results[f"{col}_recovery_days"] = (recovered.index[0] - trough).days
        else:
            results[f"{col}_recovery_days"] = None

    return results


# ==================================================================
# MAIN ANALYSIS
# ==================================================================
def main():
    # Step 1: Download data
    prices = download_data()

    # Step 2: Find all major drawdowns
    print("\n" + "=" * 70)
    print("STEP 1: Identifying Major SPY Drawdowns (>10%)")
    print("=" * 70)

    episodes = find_drawdowns(prices["SPY"], threshold=DRAWDOWN_THRESHOLD)
    print(f"\n  Found {len(episodes)} major drawdown episodes:")

    for i, ep in enumerate(episodes):
        rec_str = ep["recovery_date"].strftime("%Y-%m-%d") if ep["recovery_date"] else "N/A"
        print(f"\n  Episode {i+1}:")
        print(f"    Peak:     {ep['peak_date'].strftime('%Y-%m-%d')} (price: ${ep['peak_price']:.2f})")
        print(f"    Trough:   {ep['trough_date'].strftime('%Y-%m-%d')} (price: ${ep['trough_price']:.2f})")
        print(f"    Recovery: {rec_str}")
        print(f"    Max DD:   {ep['max_dd']:.1%}")
        print(f"    Weeks to trough: {ep['weeks_to_trough']:.1f}")
        if ep["weeks_to_recovery"] is not None:
            print(f"    Weeks to recovery: {ep['weeks_to_recovery']:.1f}")

    # Step 3: Classify each crash
    print("\n" + "=" * 70)
    print("STEP 2: Crash Classification")
    print("=" * 70)

    type_labels = {
        "A": "Demand Shock (VIX>40, GLD+)",
        "B": "Rate/Inflation Shock (VIX moderate, GLD-)",
        "C": "Correction (VIX mild, quick)",
        "D": "Liquidity Crisis (VIX>50, everything sells)",
    }

    for i, ep in enumerate(episodes):
        crash_type, info = classify_crash(ep, prices)
        ep["crash_type"] = crash_type
        ep["classification_info"] = info

        print(f"\n  Episode {i+1}: {ep['peak_date'].strftime('%Y-%m')} → {ep['trough_date'].strftime('%Y-%m')}")
        print(f"    Type: {crash_type} — {type_labels[crash_type]}")
        print(f"    VIX peak: {info['vix_peak']:.1f}")
        print(f"    GLD return (peak→trough): {info['gld_return']:.1%}")
        if "gld_around_vix_peak" in info:
            print(f"    GLD around VIX peak (±5d): {info['gld_around_vix_peak']:.1%}")

    # Step 4: Build strategies
    print("\n" + "=" * 70)
    print("STEP 3: Building Strategies")
    print("=" * 70)

    nav = build_strategies(prices)

    # Full period stats
    total_days = len(nav)
    years = total_days / 252
    for col in nav.columns:
        total_ret = nav[col].iloc[-1] / nav[col].iloc[0] - 1
        ann_ret = (1 + total_ret) ** (1 / years) - 1
        print(f"  {col:10s}: Total={total_ret:.1%}, Ann={ann_ret:.1%}")

    # Step 5: Measure crash performance
    print("\n" + "=" * 70)
    print("STEP 4: Crash-by-Crash Performance Analysis")
    print("=" * 70)

    crash_results = []
    for i, ep in enumerate(episodes):
        perf = measure_crash_performance(nav, ep)
        ep["performance"] = perf
        crash_results.append(ep)

        name = f"#{i+1} ({ep['peak_date'].strftime('%Y-%m')})"
        print(f"\n  {'─' * 60}")
        print(f"  {name} — Type {ep['crash_type']}: {type_labels[ep['crash_type']]}")
        print(f"  {'─' * 60}")
        print(f"    SPY Max DD:      {perf['SPY_dd']:.1%}")
        print(f"    50/50 Max DD:    {perf['5050_dd']:.1%}")
        print(f"    50/50+VT Max DD: {perf['5050_VT_dd']:.1%}")
        print(f"    ──────────────────────────────")
        print(f"    50/50 protection ratio:    {perf['5050_protection']:.1%}")
        print(f"    50/50+VT protection ratio: {perf['5050_VT_protection']:.1%}")
        print(f"    VT incremental:            {perf['VT_incremental']:.1%}")

    # Step 6: Summary by crash type
    print("\n" + "=" * 70)
    print("STEP 5: Summary by Crash Type")
    print("=" * 70)

    type_summary = {}
    for crash_type in ["A", "B", "C", "D"]:
        type_episodes = [ep for ep in crash_results if ep["crash_type"] == crash_type]
        if not type_episodes:
            continue

        n_episodes = len(type_episodes)
        avg_spy_dd = np.mean([ep["performance"]["SPY_dd"] for ep in type_episodes])
        avg_5050_dd = np.mean([ep["performance"]["5050_dd"] for ep in type_episodes])
        avg_5050vt_dd = np.mean([ep["performance"]["5050_VT_dd"] for ep in type_episodes])
        avg_5050_prot = np.mean([ep["performance"]["5050_protection"] for ep in type_episodes])
        avg_5050vt_prot = np.mean([ep["performance"]["5050_VT_protection"] for ep in type_episodes])
        avg_vt_incr = np.mean([ep["performance"]["VT_incremental"] for ep in type_episodes])

        # Best/worst VT protection
        vt_prots = [ep["performance"]["5050_VT_protection"] for ep in type_episodes]
        best_vt = max(vt_prots)
        worst_vt = min(vt_prots)

        type_summary[crash_type] = {
            "label": type_labels[crash_type],
            "n_episodes": n_episodes,
            "avg_spy_dd": avg_spy_dd,
            "avg_5050_dd": avg_5050_dd,
            "avg_5050vt_dd": avg_5050vt_dd,
            "avg_5050_protection": avg_5050_prot,
            "avg_5050vt_protection": avg_5050vt_prot,
            "avg_vt_incremental": avg_vt_incr,
            "best_vt_protection": best_vt,
            "worst_vt_protection": worst_vt,
        }

        print(f"\n  Type {crash_type}: {type_labels[crash_type]}")
        print(f"  {'─' * 55}")
        print(f"    Episodes: {n_episodes}")
        print(f"    Avg SPY DD:      {avg_spy_dd:.1%}")
        print(f"    Avg 50/50 DD:    {avg_5050_dd:.1%}")
        print(f"    Avg 50/50+VT DD: {avg_5050vt_dd:.1%}")
        print(f"    Avg 50/50 protection:    {avg_5050_prot:.1%}")
        print(f"    Avg 50/50+VT protection: {avg_5050vt_prot:.1%}")
        print(f"    Avg VT incremental:      {avg_vt_incr:.1%}")
        print(f"    VT protection range: [{worst_vt:.1%}, {best_vt:.1%}]")

    # Step 7: Does VT help in ALL crash types?
    print("\n" + "=" * 70)
    print("STEP 6: Key Question — Does 50/50+VT Work for ALL Crash Types?")
    print("=" * 70)

    all_vt_helps = True
    for crash_type, summary in type_summary.items():
        vt_helps = summary["avg_5050vt_protection"] > summary["avg_5050_protection"]
        status = "YES" if vt_helps else "NO"
        if not vt_helps:
            all_vt_helps = False
        print(f"\n  Type {crash_type} ({summary['label']}):")
        print(f"    VT adds value beyond 50/50? {status}")
        print(f"    VT incremental protection: {summary['avg_vt_incremental']:.1%}")

    # Per-episode VT win/loss
    print("\n\n  Per-Episode VT Win/Loss:")
    vt_wins = 0
    vt_total = 0
    for ep in crash_results:
        vt_incr = ep["performance"]["VT_incremental"]
        vt_total += 1
        if vt_incr > 0:
            vt_wins += 1
        symbol = "+" if vt_incr > 0 else "-"
        print(f"    {ep['peak_date'].strftime('%Y-%m')} Type {ep['crash_type']}: VT incr = {vt_incr:+.1%} [{symbol}]")

    print(f"\n  VT wins: {vt_wins}/{vt_total} ({vt_wins/vt_total:.0%})")

    # Step 8: Cross-type comparison table
    print("\n" + "=" * 70)
    print("STEP 7: Cross-Type Comparison Table")
    print("=" * 70)

    header = f"  {'Type':<6} {'N':>3} {'SPY DD':>10} {'5050 DD':>10} {'5050+VT DD':>12} {'5050 Prot':>10} {'VT Prot':>10} {'VT Incr':>10}"
    print(f"\n{header}")
    print(f"  {'─' * 73}")
    for crash_type in ["A", "B", "C", "D"]:
        if crash_type not in type_summary:
            continue
        s = type_summary[crash_type]
        print(f"  {crash_type:<6} {s['n_episodes']:>3} {s['avg_spy_dd']:>10.1%} {s['avg_5050_dd']:>10.1%} "
              f"{s['avg_5050vt_dd']:>12.1%} {s['avg_5050_protection']:>10.1%} "
              f"{s['avg_5050vt_protection']:>10.1%} {s['avg_vt_incremental']:>10.1%}")

    # Overall
    all_spy = np.mean([ep["performance"]["SPY_dd"] for ep in crash_results])
    all_5050 = np.mean([ep["performance"]["5050_dd"] for ep in crash_results])
    all_vt = np.mean([ep["performance"]["5050_VT_dd"] for ep in crash_results])
    all_5050_p = np.mean([ep["performance"]["5050_protection"] for ep in crash_results])
    all_vt_p = np.mean([ep["performance"]["5050_VT_protection"] for ep in crash_results])
    all_vt_i = np.mean([ep["performance"]["VT_incremental"] for ep in crash_results])

    print(f"  {'─' * 73}")
    print(f"  {'ALL':<6} {len(crash_results):>3} {all_spy:>10.1%} {all_5050:>10.1%} "
          f"{all_vt:>12.1%} {all_5050_p:>10.1%} "
          f"{all_vt_p:>10.1%} {all_vt_i:>10.1%}")

    # Step 9: Conclusions
    print("\n" + "=" * 70)
    print("CONCLUSIONS")
    print("=" * 70)

    if all_vt_helps:
        print("\n  [POSITIVE] VT adds value beyond 50/50 in ALL crash types on average.")
    else:
        print("\n  [MIXED] VT does NOT add value in all crash types equally.")
        for crash_type, summary in type_summary.items():
            if summary["avg_vt_incremental"] <= 0:
                print(f"    → Type {crash_type} ({summary['label']}): VT incremental = {summary['avg_vt_incremental']:.1%}")

    print(f"\n  Overall VT win rate: {vt_wins}/{vt_total} ({vt_wins/vt_total:.0%}) of crashes")
    print(f"  Average VT incremental protection: {all_vt_i:.1%}")

    # Identify which crash type benefits most/least
    if type_summary:
        best_type = max(type_summary.items(), key=lambda x: x[1]["avg_vt_incremental"])
        worst_type = min(type_summary.items(), key=lambda x: x[1]["avg_vt_incremental"])
        print(f"\n  Best crash type for VT:  Type {best_type[0]} ({best_type[1]['label']}) = {best_type[1]['avg_vt_incremental']:.1%}")
        print(f"  Worst crash type for VT: Type {worst_type[0]} ({worst_type[1]['label']}) = {worst_type[1]['avg_vt_incremental']:.1%}")

    # Step 10: Additional analysis — GLD contribution
    print("\n" + "=" * 70)
    print("STEP 8: GLD Contribution During Each Crash")
    print("=" * 70)

    for i, ep in enumerate(crash_results):
        peak = ep["peak_date"]
        trough = ep["trough_date"]
        mask = (prices.index >= peak) & (prices.index <= trough)
        crash_prices = prices.loc[mask]

        if len(crash_prices) < 2:
            continue

        spy_crash_ret = crash_prices["SPY"].iloc[-1] / crash_prices["SPY"].iloc[0] - 1
        gld_crash_ret = crash_prices["GLD"].iloc[-1] / crash_prices["GLD"].iloc[0] - 1

        # Correlation during crash
        spy_daily = crash_prices["SPY"].pct_change().dropna()
        gld_daily = crash_prices["GLD"].pct_change().dropna()
        if len(spy_daily) > 5:
            corr = spy_daily.corr(gld_daily)
        else:
            corr = np.nan

        gld_status = "HEDGE" if gld_crash_ret > 0 else "CO-CRASH"

        name = f"#{i+1} ({ep['peak_date'].strftime('%Y-%m')})"
        print(f"  {name} Type {ep['crash_type']}: SPY={spy_crash_ret:+.1%}, GLD={gld_crash_ret:+.1%}, "
              f"Corr={corr:+.2f}, GLD={gld_status}")

    # Save results
    print("\n" + "=" * 70)
    print("Saving results...")
    print("=" * 70)

    save_results = {
        "experiment": "K273",
        "title": "Crash Taxonomy — Are All Crashes the Same for 50/50+VT?",
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{prices.index[0].date()} to {prices.index[-1].date()}",
        "n_trading_days": len(prices),
        "drawdown_threshold": DRAWDOWN_THRESHOLD,
        "n_crashes_found": len(crash_results),
        "vt_win_rate": f"{vt_wins}/{vt_total}",
        "avg_vt_incremental_protection": round(all_vt_i, 4),
        "type_summary": {},
        "crashes": [],
    }

    for crash_type, summary in type_summary.items():
        save_results["type_summary"][f"Type_{crash_type}"] = {
            "label": summary["label"],
            "n_episodes": summary["n_episodes"],
            "avg_spy_dd": round(summary["avg_spy_dd"], 4),
            "avg_5050_dd": round(summary["avg_5050_dd"], 4),
            "avg_5050vt_dd": round(summary["avg_5050vt_dd"], 4),
            "avg_5050_protection": round(summary["avg_5050_protection"], 4),
            "avg_5050vt_protection": round(summary["avg_5050vt_protection"], 4),
            "avg_vt_incremental": round(summary["avg_vt_incremental"], 4),
        }

    for ep in crash_results:
        crash_entry = {
            "peak_date": ep["peak_date"].strftime("%Y-%m-%d"),
            "trough_date": ep["trough_date"].strftime("%Y-%m-%d"),
            "recovery_date": ep["recovery_date"].strftime("%Y-%m-%d") if ep["recovery_date"] else None,
            "max_dd": round(ep["max_dd"], 4),
            "weeks_to_trough": round(ep["weeks_to_trough"], 1),
            "weeks_to_recovery": round(ep["weeks_to_recovery"], 1) if ep["weeks_to_recovery"] else None,
            "crash_type": ep["crash_type"],
            "vix_peak": round(ep["classification_info"]["vix_peak"], 1),
            "gld_return": round(ep["classification_info"]["gld_return"], 4),
            "spy_dd": round(ep["performance"]["SPY_dd"], 4),
            "dd_5050": round(ep["performance"]["5050_dd"], 4),
            "dd_5050vt": round(ep["performance"]["5050_VT_dd"], 4),
            "protection_5050": round(ep["performance"]["5050_protection"], 4),
            "protection_5050vt": round(ep["performance"]["5050_VT_protection"], 4),
            "vt_incremental": round(ep["performance"]["VT_incremental"], 4),
        }
        save_results["crashes"].append(crash_entry)

    results_path = "experiments/k273_crash_taxonomy_results.json"
    with open(results_path, "w") as f:
        json.dump(save_results, f, indent=2)
    print(f"  Results saved to {results_path}")

    print("\n" + "=" * 70)
    print("K273 COMPLETE")
    print("=" * 70)

    return save_results


if __name__ == "__main__":
    results = main()
