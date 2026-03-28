"""
K648: Drawdown Recovery Speed Analysis
=======================================
Motivation: K641 showed Piecewise has best protection but slowest rebound capture.
For investors, recovery speed matters as much as drawdown depth.

This experiment analyzes:
1. All drawdown episodes >2% for each strategy
2. Recovery time from trough to new high
3. Ulcer index, Pain index, Pain-adjusted Sharpe
4. Monthly loss probability (practical insight)

Data source: paper_trading.json (2023-01 to 2026-03)
Benchmark: SPY buy-and-hold (constructed from paper_trading returns)

References:
- Martin (1987) "An Exact Measure of Risk" - Ulcer Index
- Keating & Shadwick (2002) "A Universal Performance Measure" - Pain ratio concept
- Bacon (2008) "Practical Portfolio Performance Measurement" - Underwater analysis
"""

import json
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sys

# ── Configuration ──────────────────────────────────────────────────────
DRAWDOWN_THRESHOLD = 0.02  # 2% minimum drawdown to count as episode
ANNUALIZATION_FACTOR = 252  # trading days per year

# Strategy display names
DISPLAY_NAMES = {
    "slow_vt": "GARCH VT (SPY)",
    "risk_parity": "Risk Parity (SPY+GLD)",
    "simple_12vix": "12/VIX (SPY)",
    "recommended_5050": "50/50 SPY/GLD",
    "taiwan_8.63vix": "Taiwan VT (0050.TW)",
    "taiwan_spy_momentum": "Taiwan Momentum",
    "tz_tw_jp_5050": "TW+JP 50/50 TZ",
    "global_vt_tz": "Global US VT + TW TZ",
    "vix_leading_guard": "VIX+Leading (0050.TW)",
    "vix_cond_leverage": "VIX Cond Leverage",
    "taiwan_hybrid_leverage": "Taiwan Hybrid Leverage",
    "piecewise_conservative": "Piecewise Conservative",
    "fear_dca": "Fear DCA",
    "spy_buyhold": "SPY Buy & Hold",
}

# Active strategies to analyze (include inactive for completeness)
ACTIVE_STRATEGIES = [
    "slow_vt", "risk_parity", "simple_12vix", "recommended_5050",
    "taiwan_8.63vix", "vix_leading_guard", "vix_cond_leverage",
    "taiwan_hybrid_leverage", "piecewise_conservative", "fear_dca",
]


def load_data():
    """Load paper_trading.json and construct SPY buy-and-hold."""
    base = Path(__file__).resolve().parent.parent
    pt_path = base / "storage" / "paper_trading.json"
    with open(pt_path) as f:
        data = json.load(f)

    strategies = {}
    for key in ACTIVE_STRATEGIES:
        if key not in data:
            continue
        entries = data[key]["entries"]
        dates = []
        returns = []
        for e in entries:
            r = e.get("portfolio_return")
            if r is not None:
                dates.append(e["data_date"])
                returns.append(float(r))
        strategies[key] = {"dates": dates, "returns": np.array(returns)}

    # Construct SPY buy-and-hold from slow_vt dates
    # We need actual SPY returns. We can extract them from a strategy that holds
    # SPY with varying weights. Instead, let's approximate from simple_12vix
    # which holds only SPY. Better: use yfinance to get actual SPY data.
    try:
        import yfinance as yf
        # Get SPY data for the same period
        spy = yf.download("SPY", start="2023-01-01", end="2026-03-28",
                          progress=False, auto_adjust=True)
        spy_returns = spy["Close"].pct_change().dropna()
        spy_dates = [d.strftime("%Y-%m-%d") for d in spy_returns.index]
        strategies["spy_buyhold"] = {
            "dates": spy_dates,
            "returns": spy_returns.values,
        }
        print(f"SPY buy-and-hold: {len(spy_dates)} days loaded via yfinance")
    except Exception as e:
        print(f"Warning: Could not load SPY data via yfinance: {e}")
        print("Using simple_12vix as SPY proxy (holds only SPY)")
        # Fallback: use the strategy with highest SPY weight as proxy
        if "simple_12vix" in strategies:
            strategies["spy_buyhold"] = {
                "dates": strategies["simple_12vix"]["dates"].copy(),
                "returns": strategies["simple_12vix"]["returns"].copy(),
            }

    return strategies


def compute_cumulative(returns):
    """Compute cumulative wealth index (starting at 1.0)."""
    return np.cumprod(1 + returns)


def find_drawdown_episodes(dates, returns, threshold=DRAWDOWN_THRESHOLD):
    """
    Identify all drawdown episodes exceeding the threshold.

    Returns list of dicts with:
    - peak_date, peak_idx: when the high-water mark was set
    - trough_date, trough_idx: when drawdown was deepest
    - recovery_date, recovery_idx: when wealth returned to peak (None if not recovered)
    - depth: maximum drawdown (negative number)
    - days_to_trough: trading days from peak to trough
    - recovery_days: trading days from trough to recovery (None if not recovered)
    - total_underwater: total trading days below peak
    - pain_index: |depth| * total_underwater
    """
    wealth = compute_cumulative(returns)
    n = len(wealth)

    episodes = []
    hwm = wealth[0]  # high-water mark
    hwm_idx = 0
    in_drawdown = False
    current_episode = None

    for i in range(n):
        if wealth[i] >= hwm:
            # New high or recovery
            if in_drawdown and current_episode is not None:
                # Check if this drawdown was significant enough
                if abs(current_episode["depth"]) >= threshold:
                    current_episode["recovery_date"] = dates[i]
                    current_episode["recovery_idx"] = i
                    current_episode["recovery_days"] = (
                        i - current_episode["trough_idx"]
                    )
                    current_episode["total_underwater"] = (
                        i - current_episode["peak_idx"]
                    )
                    episodes.append(current_episode)
                in_drawdown = False
                current_episode = None
            hwm = wealth[i]
            hwm_idx = i
        else:
            dd = (wealth[i] - hwm) / hwm  # negative number
            if not in_drawdown:
                # Start new potential drawdown episode
                in_drawdown = True
                current_episode = {
                    "peak_date": dates[hwm_idx],
                    "peak_idx": hwm_idx,
                    "trough_date": dates[i],
                    "trough_idx": i,
                    "depth": dd,
                    "recovery_date": None,
                    "recovery_idx": None,
                    "recovery_days": None,
                    "total_underwater": None,
                }
            else:
                if dd < current_episode["depth"]:
                    current_episode["trough_date"] = dates[i]
                    current_episode["trough_idx"] = i
                    current_episode["depth"] = dd

    # Handle ongoing drawdown (not yet recovered)
    if in_drawdown and current_episode is not None:
        if abs(current_episode["depth"]) >= threshold:
            current_episode["total_underwater"] = n - 1 - current_episode["peak_idx"]
            episodes.append(current_episode)

    # Calculate days_to_trough and pain_index for all episodes
    for ep in episodes:
        ep["days_to_trough"] = ep["trough_idx"] - ep["peak_idx"]
        underwater = ep["total_underwater"] if ep["total_underwater"] else (
            n - 1 - ep["peak_idx"]
        )
        ep["pain_index"] = abs(ep["depth"]) * underwater

    return episodes


def compute_ulcer_index(returns):
    """
    Ulcer Index = sqrt(mean(drawdown²))
    where drawdown is measured from running high-water mark.
    Martin (1987).
    """
    wealth = compute_cumulative(returns)
    hwm = np.maximum.accumulate(wealth)
    dd = (wealth - hwm) / hwm  # all <= 0
    return np.sqrt(np.mean(dd ** 2))


def compute_sharpe(returns, rf_annual=0.04):
    """Annualized Sharpe ratio assuming daily returns."""
    daily_rf = (1 + rf_annual) ** (1 / 252) - 1
    excess = returns - daily_rf
    if np.std(excess) == 0:
        return 0.0
    return np.mean(excess) / np.std(excess) * np.sqrt(252)


def compute_drawdown_series(returns):
    """Compute drawdown at each point (for Ulcer calc and visualization)."""
    wealth = compute_cumulative(returns)
    hwm = np.maximum.accumulate(wealth)
    return (wealth - hwm) / hwm


def monthly_loss_probability(dates, returns):
    """
    For an investor checking monthly, what % of months show a loss?
    Group by year-month, compute monthly return, count negative months.
    """
    monthly = {}
    for d, r in zip(dates, returns):
        ym = d[:7]  # YYYY-MM
        if ym not in monthly:
            monthly[ym] = []
        monthly[ym].append(r)

    monthly_returns = {}
    for ym, rets in monthly.items():
        # Compound daily returns within month
        monthly_returns[ym] = np.prod(1 + np.array(rets)) - 1

    total_months = len(monthly_returns)
    loss_months = sum(1 for r in monthly_returns.values() if r < 0)
    avg_loss = np.mean([r for r in monthly_returns.values() if r < 0]) if loss_months > 0 else 0
    avg_gain = np.mean([r for r in monthly_returns.values() if r >= 0]) if (total_months - loss_months) > 0 else 0

    return {
        "total_months": total_months,
        "loss_months": loss_months,
        "loss_probability": loss_months / total_months if total_months > 0 else 0,
        "avg_monthly_loss": float(avg_loss),
        "avg_monthly_gain": float(avg_gain),
        "monthly_returns": {ym: float(r) for ym, r in sorted(monthly_returns.items())},
    }


def analyze_strategy(key, dates, returns):
    """Full drawdown analysis for a single strategy."""
    episodes = find_drawdown_episodes(dates, returns)
    ulcer = compute_ulcer_index(returns)
    sharpe = compute_sharpe(returns)
    dd_series = compute_drawdown_series(returns)
    monthly = monthly_loss_probability(dates, returns)

    # Cumulative return
    total_return = float(np.prod(1 + returns) - 1)
    n_days = len(returns)
    ann_return = float((1 + total_return) ** (252 / n_days) - 1)

    # Max drawdown
    max_dd = float(np.min(dd_series))

    # Episode statistics
    recovered = [ep for ep in episodes if ep["recovery_date"] is not None]
    unrecovered = [ep for ep in episodes if ep["recovery_date"] is None]

    avg_recovery = (
        float(np.mean([ep["recovery_days"] for ep in recovered]))
        if recovered else None
    )
    median_recovery = (
        float(np.median([ep["recovery_days"] for ep in recovered]))
        if recovered else None
    )
    max_recovery = (
        int(max(ep["recovery_days"] for ep in recovered))
        if recovered else None
    )

    avg_underwater = (
        float(np.mean([ep["total_underwater"] for ep in episodes if ep["total_underwater"]]))
        if episodes else 0
    )
    max_underwater = (
        int(max(ep["total_underwater"] for ep in episodes if ep["total_underwater"]))
        if episodes else 0
    )

    avg_depth = (
        float(np.mean([ep["depth"] for ep in episodes]))
        if episodes else 0
    )

    avg_pain = (
        float(np.mean([ep["pain_index"] for ep in episodes]))
        if episodes else 0
    )

    # Pain-adjusted Sharpe = Sharpe / Ulcer Index (Martin ratio)
    pain_adj_sharpe = sharpe / ulcer if ulcer > 0 else float("inf")

    # Pain ratio = avg(|depth| * days_underwater) / Sharpe
    pain_ratio = avg_pain / sharpe if sharpe > 0 else float("inf")

    # Percentage of time underwater
    pct_underwater = float(np.mean(dd_series < -0.001))  # below -0.1%

    return {
        "strategy": key,
        "display_name": DISPLAY_NAMES.get(key, key),
        "n_days": n_days,
        "date_range": f"{dates[0]} to {dates[-1]}",
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(ann_return * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sharpe": round(sharpe, 3),
        "ulcer_index": round(ulcer, 5),
        "pain_adjusted_sharpe": round(pain_adj_sharpe, 2),
        "n_episodes": len(episodes),
        "n_recovered": len(recovered),
        "n_unrecovered": len(unrecovered),
        "avg_recovery_days": round(avg_recovery, 1) if avg_recovery else None,
        "median_recovery_days": round(median_recovery, 1) if median_recovery else None,
        "max_recovery_days": max_recovery,
        "avg_underwater_days": round(avg_underwater, 1),
        "max_underwater_days": max_underwater,
        "avg_depth_pct": round(avg_depth * 100, 2),
        "avg_pain_index": round(avg_pain, 4),
        "pain_ratio": round(pain_ratio, 2) if pain_ratio != float("inf") else "inf",
        "pct_time_underwater": round(pct_underwater * 100, 1),
        "monthly_loss_probability_pct": round(monthly["loss_probability"] * 100, 1),
        "avg_monthly_loss_pct": round(monthly["avg_monthly_loss"] * 100, 2),
        "avg_monthly_gain_pct": round(monthly["avg_monthly_gain"] * 100, 2),
        "episodes": [
            {
                "peak_date": ep["peak_date"],
                "trough_date": ep["trough_date"],
                "recovery_date": ep["recovery_date"],
                "depth_pct": round(ep["depth"] * 100, 2),
                "days_to_trough": ep["days_to_trough"],
                "recovery_days": ep["recovery_days"],
                "total_underwater": ep["total_underwater"],
                "pain_index": round(ep["pain_index"], 4),
            }
            for ep in episodes
        ],
    }


def rank_strategies(results):
    """Create ranking tables across multiple dimensions."""
    # Only rank strategies with comparable date ranges (US-based, 2023+)
    # Filter out strategies with very different start dates for fair comparison
    rankings = {}

    # a. Fastest average recovery (lower is better)
    valid = [(r["strategy"], r["avg_recovery_days"])
             for r in results if r["avg_recovery_days"] is not None]
    valid.sort(key=lambda x: x[1])
    rankings["fastest_avg_recovery"] = [
        {"rank": i + 1, "strategy": DISPLAY_NAMES.get(s, s),
         "key": s, "avg_recovery_days": v}
        for i, (s, v) in enumerate(valid)
    ]

    # b. Shortest max underwater time (lower is better)
    valid = [(r["strategy"], r["max_underwater_days"])
             for r in results if r["max_underwater_days"] > 0]
    valid.sort(key=lambda x: x[1])
    rankings["shortest_max_underwater"] = [
        {"rank": i + 1, "strategy": DISPLAY_NAMES.get(s, s),
         "key": s, "max_underwater_days": v}
        for i, (s, v) in enumerate(valid)
    ]

    # c. Lowest Ulcer index (lower is better)
    valid = [(r["strategy"], r["ulcer_index"]) for r in results]
    valid.sort(key=lambda x: x[1])
    rankings["lowest_ulcer_index"] = [
        {"rank": i + 1, "strategy": DISPLAY_NAMES.get(s, s),
         "key": s, "ulcer_index": v}
        for i, (s, v) in enumerate(valid)
    ]

    # d. Best Pain-adjusted Sharpe (higher is better)
    valid = [(r["strategy"], r["pain_adjusted_sharpe"])
             for r in results if r["pain_adjusted_sharpe"] != float("inf")]
    valid.sort(key=lambda x: x[1], reverse=True)
    rankings["best_pain_adjusted_sharpe"] = [
        {"rank": i + 1, "strategy": DISPLAY_NAMES.get(s, s),
         "key": s, "pain_adjusted_sharpe": v}
        for i, (s, v) in enumerate(valid)
    ]

    # e. Lowest monthly loss probability (lower is better)
    valid = [(r["strategy"], r["monthly_loss_probability_pct"]) for r in results]
    valid.sort(key=lambda x: x[1])
    rankings["lowest_monthly_loss_prob"] = [
        {"rank": i + 1, "strategy": DISPLAY_NAMES.get(s, s),
         "key": s, "monthly_loss_probability_pct": v}
        for i, (s, v) in enumerate(valid)
    ]

    return rankings


def print_summary(results, rankings):
    """Print formatted summary tables."""
    print("\n" + "=" * 90)
    print("K648: DRAWDOWN RECOVERY SPEED ANALYSIS")
    print("=" * 90)

    # Summary table
    print("\n── Strategy Overview ──")
    header = f"{'Strategy':<28} {'Return%':>8} {'MDD%':>7} {'Sharpe':>7} {'Ulcer':>8} {'Episodes':>8}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x["sharpe"], reverse=True):
        name = r["display_name"][:27]
        print(f"{name:<28} {r['total_return_pct']:>7.1f}% {r['max_drawdown_pct']:>6.1f}% "
              f"{r['sharpe']:>7.3f} {r['ulcer_index']:>8.5f} {r['n_episodes']:>8}")

    # Recovery speed table
    print("\n── Recovery Speed ──")
    header = f"{'Strategy':<28} {'Avg Rec':>8} {'Med Rec':>8} {'Max Rec':>8} {'Max UW':>8} {'%UW':>6}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x["avg_recovery_days"] or 999):
        name = r["display_name"][:27]
        avg_rec = f"{r['avg_recovery_days']:.0f}d" if r["avg_recovery_days"] else "N/A"
        med_rec = f"{r['median_recovery_days']:.0f}d" if r["median_recovery_days"] else "N/A"
        max_rec = f"{r['max_recovery_days']}d" if r["max_recovery_days"] else "N/A"
        max_uw = f"{r['max_underwater_days']}d" if r["max_underwater_days"] else "N/A"
        print(f"{name:<28} {avg_rec:>8} {med_rec:>8} {max_rec:>8} {max_uw:>8} {r['pct_time_underwater']:>5.1f}%")

    # Pain analysis
    print("\n── Pain Analysis ──")
    header = f"{'Strategy':<28} {'Avg Depth':>10} {'Avg Pain':>10} {'Pain Ratio':>11} {'PAS':>8}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x["pain_adjusted_sharpe"], reverse=True):
        name = r["display_name"][:27]
        pr = f"{r['pain_ratio']}" if isinstance(r["pain_ratio"], str) else f"{r['pain_ratio']:.2f}"
        print(f"{name:<28} {r['avg_depth_pct']:>9.2f}% {r['avg_pain_index']:>10.4f} {pr:>11} {r['pain_adjusted_sharpe']:>8.1f}")

    # Monthly loss probability (practical insight)
    print("\n── Practical Insight: Monthly Check ──")
    print("For an investor who checks their portfolio once a month:")
    header = f"{'Strategy':<28} {'Loss%':>7} {'Avg Loss':>10} {'Avg Gain':>10} {'Gain/Loss':>10}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x["monthly_loss_probability_pct"]):
        name = r["display_name"][:27]
        gl_ratio = abs(r["avg_monthly_gain_pct"] / r["avg_monthly_loss_pct"]) if r["avg_monthly_loss_pct"] != 0 else float("inf")
        gl_str = f"{gl_ratio:.2f}" if gl_ratio != float("inf") else "inf"
        print(f"{name:<28} {r['monthly_loss_probability_pct']:>6.1f}% {r['avg_monthly_loss_pct']:>9.2f}% "
              f"{r['avg_monthly_gain_pct']:>9.2f}% {gl_str:>10}")

    # Rankings summary
    print("\n── Rankings Summary ──")
    for rk_name, rk_list in rankings.items():
        label = rk_name.replace("_", " ").title()
        top3 = ", ".join(f"{r['rank']}. {r['strategy']}" for r in rk_list[:3])
        print(f"  {label}: {top3}")

    # Worst drawdown episodes across all strategies
    print("\n── Top 10 Worst Drawdown Episodes ──")
    all_episodes = []
    for r in results:
        for ep in r["episodes"]:
            all_episodes.append({
                "strategy": r["display_name"],
                **ep,
            })
    all_episodes.sort(key=lambda x: x["depth_pct"])
    header = f"{'Strategy':<28} {'Peak':>12} {'Trough':>12} {'Recovery':>12} {'Depth':>7} {'UW days':>8}"
    print(header)
    print("-" * len(header))
    for ep in all_episodes[:10]:
        rec = ep["recovery_date"] if ep["recovery_date"] else "ongoing"
        uw = ep["total_underwater"] if ep["total_underwater"] else "---"
        print(f"{ep['strategy']:<28} {ep['peak_date']:>12} {ep['trough_date']:>12} "
              f"{rec:>12} {ep['depth_pct']:>6.1f}% {str(uw):>8}")


def main():
    print("Loading data...")
    strategies = load_data()
    print(f"Loaded {len(strategies)} strategies")

    results = []
    for key, data in strategies.items():
        print(f"  Analyzing {key} ({len(data['returns'])} days)...")
        result = analyze_strategy(key, data["dates"], data["returns"])
        results.append(result)

    rankings = rank_strategies(results)
    print_summary(results, rankings)

    # ── Save results ──
    output = {
        "experiment_id": "K648",
        "title": "Drawdown Recovery Speed Analysis",
        "description": (
            "Comprehensive analysis of drawdown episodes, recovery speed, "
            "Ulcer index, Pain index, and monthly loss probability for all "
            "VolPred strategies vs SPY buy-and-hold."
        ),
        "data_source": "paper_trading.json + yfinance (SPY)",
        "methodology": {
            "drawdown_threshold": f"{DRAWDOWN_THRESHOLD*100}%",
            "metrics": [
                "Episode identification (peak->trough->recovery)",
                "Ulcer Index (Martin 1987)",
                "Pain Index (depth * underwater days)",
                "Pain-adjusted Sharpe (Sharpe / Ulcer)",
                "Monthly loss probability",
            ],
            "references": [
                "Martin, P. (1987). 'An Exact Measure of Risk: The Ulcer Index'",
                "Keating, C. & Shadwick, W.F. (2002). 'A Universal Performance Measure'",
                "Bacon, C.R. (2008). 'Practical Portfolio Performance Measurement and Attribution'",
            ],
        },
        "strategy_results": {r["strategy"]: r for r in results},
        "rankings": rankings,
        "practical_insight": {
            "question": "For an investor who checks monthly, which strategy minimizes chance of seeing a loss?",
            "answer": None,  # Will be filled below
        },
        "key_findings": [],  # Will be filled below
    }

    # Determine practical insight answer
    best_monthly = min(results, key=lambda x: x["monthly_loss_probability_pct"])
    output["practical_insight"]["answer"] = (
        f"{best_monthly['display_name']} has the lowest monthly loss probability "
        f"at {best_monthly['monthly_loss_probability_pct']}%, meaning an investor "
        f"checking monthly would see a loss only {best_monthly['monthly_loss_probability_pct']}% "
        f"of the time."
    )

    # Key findings
    best_recovery = min(
        [r for r in results if r["avg_recovery_days"] is not None],
        key=lambda x: x["avg_recovery_days"],
    )
    best_ulcer = min(results, key=lambda x: x["ulcer_index"])
    best_pas = max(
        [r for r in results if isinstance(r["pain_adjusted_sharpe"], (int, float))
         and r["pain_adjusted_sharpe"] != float("inf")],
        key=lambda x: x["pain_adjusted_sharpe"],
    )
    worst_recovery = max(
        [r for r in results if r["avg_recovery_days"] is not None],
        key=lambda x: x["avg_recovery_days"],
    )

    spy_result = next((r for r in results if r["strategy"] == "spy_buyhold"), None)

    output["key_findings"] = [
        f"Fastest average recovery: {best_recovery['display_name']} at {best_recovery['avg_recovery_days']:.1f} days",
        f"Lowest Ulcer Index: {best_ulcer['display_name']} at {best_ulcer['ulcer_index']:.5f}",
        f"Best Pain-adjusted Sharpe: {best_pas['display_name']} at {best_pas['pain_adjusted_sharpe']:.1f}",
        f"Slowest average recovery: {worst_recovery['display_name']} at {worst_recovery['avg_recovery_days']:.1f} days",
        f"Best monthly check strategy: {best_monthly['display_name']} ({best_monthly['monthly_loss_probability_pct']}% loss months)",
    ]
    if spy_result:
        output["key_findings"].append(
            f"SPY buy-and-hold comparison: Ulcer={spy_result['ulcer_index']:.5f}, "
            f"Sharpe={spy_result['sharpe']:.3f}, Monthly loss={spy_result['monthly_loss_probability_pct']}%"
        )

    # Print key findings
    print("\n── KEY FINDINGS ──")
    for f in output["key_findings"]:
        print(f"  * {f}")

    # Save
    out_path = Path(__file__).resolve().parent / "k648_results.json"
    # Clean up episodes for JSON (remove very long episode lists)
    output_clean = json.loads(json.dumps(output, default=str))
    with open(out_path, "w") as f:
        json.dump(output_clean, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
