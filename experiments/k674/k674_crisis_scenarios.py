"""
K674: What-If Crisis Scenarios — How Would Our Strategies Handle Future Crises?

Uses ACTUAL historical crisis data from 5 episodes (GFC, COVID, Rate Shock, Dot-com,
Flash Crash) to show what happens to a $100K portfolio under each strategy.

Strategies tested:
  1. Buy & Hold SPY (benchmark)
  2. 12/VIX SPY
  3. 50/50 SPY/GLD with 12/VIX sizing
  4. Piecewise Conservative (50/50 SPY/GLD)

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
References:
  - Moreira & Muir (2017), "Volatility-Managed Portfolios", JF
  - Fleming et al. (2001), "The economic value of volatility timing", JFE
  - VolPred K569/K574: Piecewise conservative strategy design

Author: VolPred Research System
"""

import json
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────
# 1. Download data
# ─────────────────────────────────────────────────────────────
print("=" * 70)
print("K674: What-If Crisis Scenarios")
print("=" * 70)

START = "2006-01-01"
END = "2026-03-27"

print(f"\nDownloading SPY, GLD, ^VIX from {START} to {END}...")

spy_raw = yf.download("SPY", start=START, end=END, auto_adjust=True, progress=False)
gld_raw = yf.download("GLD", start=START, end=END, auto_adjust=True, progress=False)
vix_raw = yf.download("^VIX", start=START, end=END, auto_adjust=True, progress=False)

# Flatten MultiIndex columns if present
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw["Close"].dropna()
gld = gld_raw["Close"].dropna()
vix = vix_raw["Close"].dropna()

# Align all series on common dates
common_idx = spy.index.intersection(gld.index).intersection(vix.index)
spy = spy.loc[common_idx]
gld = gld.loc[common_idx]
vix = vix.loc[common_idx]

spy_ret = spy.pct_change().fillna(0)
gld_ret = gld.pct_change().fillna(0)

print(f"  Common trading days: {len(common_idx)}")
print(f"  Date range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")
print(f"  SPY range: ${spy.iloc[0]:.2f} to ${spy.iloc[-1]:.2f}")
print(f"  VIX range: {vix.min():.1f} to {vix.max():.1f}")

# ─────────────────────────────────────────────────────────────
# 2. Strategy weight functions (matching daily_update.py logic)
# ─────────────────────────────────────────────────────────────

def calc_12vix_weight(vix_level):
    """12/VIX SPY-only strategy."""
    return min(12.0 / vix_level, 1.0) if vix_level > 0 else 1.0


def calc_5050_12vix_weights(vix_level):
    """50/50 SPY/GLD with 12/VIX sizing."""
    w = min(12.0 / vix_level, 1.0) if vix_level > 0 else 1.0
    return 0.5 * w, 0.5 * w  # spy_w, gld_w


def calc_piecewise_weights(vix_level):
    """Piecewise conservative: 50/50 SPY/GLD with VIX-based ramp.
    VIX < 12  -> w = 1.0 (fully invested)
    12 <= VIX <= 20 -> w = (20 - VIX) / 8 (linear ramp-down)
    VIX > 20  -> w = 0.0 (fully cash)
    """
    if vix_level < 12:
        pw_w = 1.0
    elif vix_level <= 20:
        pw_w = (20 - vix_level) / 8
    else:
        pw_w = 0.0
    return 0.5 * pw_w, 0.5 * pw_w  # spy_w, gld_w


# ─────────────────────────────────────────────────────────────
# 3. Simulate strategy returns over a period
# ─────────────────────────────────────────────────────────────

def simulate_strategies(start_date, end_date, spy_series, gld_series, vix_series,
                        spy_returns, gld_returns):
    """Simulate 4 strategies over a date range. Returns cumulative NAV (starting $100K)."""

    mask = (spy_series.index >= pd.Timestamp(start_date)) & \
           (spy_series.index <= pd.Timestamp(end_date))
    dates = spy_series.index[mask]

    if len(dates) < 2:
        return None

    initial = 100_000.0
    results = {
        "BH_SPY": [initial],
        "12VIX_SPY": [initial],
        "5050_12VIX": [initial],
        "Piecewise": [initial],
    }
    date_list = [dates[0]]

    for i in range(1, len(dates)):
        dt = dates[i]
        r_spy = spy_returns.loc[dt]
        r_gld = gld_returns.loc[dt]
        v = vix_series.loc[dates[i - 1]]  # use previous day's VIX for weight

        # Buy & Hold SPY
        results["BH_SPY"].append(results["BH_SPY"][-1] * (1 + r_spy))

        # 12/VIX SPY
        w = calc_12vix_weight(v)
        port_ret = w * r_spy + (1 - w) * 0  # cash earns 0 for simplicity
        results["12VIX_SPY"].append(results["12VIX_SPY"][-1] * (1 + port_ret))

        # 50/50 SPY/GLD 12/VIX
        ws, wg = calc_5050_12vix_weights(v)
        port_ret = ws * r_spy + wg * r_gld + (1 - ws - wg) * 0
        results["5050_12VIX"].append(results["5050_12VIX"][-1] * (1 + port_ret))

        # Piecewise Conservative
        ps, pg = calc_piecewise_weights(v)
        port_ret = ps * r_spy + pg * r_gld + (1 - ps - pg) * 0
        results["Piecewise"].append(results["Piecewise"][-1] * (1 + port_ret))

        date_list.append(dt)

    nav_df = pd.DataFrame(results, index=date_list)
    return nav_df


def compute_crisis_metrics(nav_df, scenario_name):
    """Compute peak-to-trough, time underwater, recovery time for each strategy."""
    metrics = {}

    for strat in nav_df.columns:
        series = nav_df[strat]
        initial = series.iloc[0]

        # Peak-to-trough drawdown
        running_max = series.cummax()
        drawdown = (series - running_max) / running_max
        max_dd = drawdown.min()
        trough_idx = drawdown.idxmin()
        trough_value = series.loc[trough_idx]

        # Dollar loss from peak
        peak_before_trough = running_max.loc[trough_idx]
        dollar_loss = trough_value - peak_before_trough

        # Time underwater: total calendar days where NAV < running high watermark
        # Recovery: calendar days from trough to when NAV returns to pre-trough peak
        underwater_days_count = 0
        first_underwater = None
        last_underwater = None
        for dt in series.index:
            if series.loc[dt] < running_max.loc[dt] * 0.999:  # 0.1% tolerance
                underwater_days_count += 1
                if first_underwater is None:
                    first_underwater = dt
                last_underwater = dt

        # Recovery from trough: find first date AFTER trough where NAV >= pre-trough peak
        recovery_days = None
        post_trough = series.loc[trough_idx:]
        for dt in post_trough.index[1:]:  # skip trough itself
            if series.loc[dt] >= peak_before_trough * 0.999:
                recovery_days = (dt - trough_idx).days
                break

        # If never recovered within the window
        if recovery_days is None and max_dd < -0.001:
            recovery_days = None  # explicitly None = "did not recover"

        # Total underwater span (calendar days)
        if first_underwater is not None and last_underwater is not None:
            underwater_span = (last_underwater - first_underwater).days
        else:
            underwater_span = 0

        # Final value
        final_value = series.iloc[-1]
        total_return = (final_value / initial - 1) * 100

        # VIX behavior during crisis (from the common vix series)
        vix_slice = vix.loc[nav_df.index[0]:nav_df.index[-1]]
        vix_peak = float(vix_slice.max()) if len(vix_slice) > 0 else None
        vix_avg = float(vix_slice.mean()) if len(vix_slice) > 0 else None

        metrics[strat] = {
            "max_drawdown_pct": round(max_dd * 100, 2),
            "peak_to_trough_dollar": round(float(dollar_loss), 0),
            "trough_date": trough_idx.strftime("%Y-%m-%d"),
            "underwater_trading_days": underwater_days_count,
            "underwater_span_calendar_days": underwater_span,
            "recovery_from_trough_days": recovery_days,
            "final_value": round(float(final_value), 0),
            "total_return_pct": round(total_return, 2),
            "vix_peak": round(vix_peak, 1) if vix_peak else None,
            "vix_avg": round(vix_avg, 1) if vix_avg else None,
        }

    return metrics


# ─────────────────────────────────────────────────────────────
# 4. Define 5 crisis scenarios (actual historical periods)
# ─────────────────────────────────────────────────────────────

SCENARIOS = {
    "GFC (2008-09)": {
        "description": "Global Financial Crisis: SPY -56% peak-to-trough, VIX peaked at 80, GLD +25%",
        "start": "2007-10-01",
        "end": "2009-06-30",
        "type": "Prolonged bear (21 months)",
        "historical_spy_dd": -56.8,
        "historical_vix_peak": 80.9,
    },
    "COVID Crash (2020)": {
        "description": "COVID-19 pandemic crash: SPY -34% in 23 trading days, VIX peaked at 82, V-shaped recovery",
        "start": "2020-02-01",
        "end": "2020-08-31",
        "type": "Rapid crash + V-recovery (7 months)",
        "historical_spy_dd": -33.9,
        "historical_vix_peak": 82.7,
    },
    "Rate Shock (2022)": {
        "description": "Fed rate hiking cycle: SPY -25% over 9 months, VIX to 36, GLD -15%, no safe haven",
        "start": "2022-01-01",
        "end": "2022-12-31",
        "type": "Slow grind (12 months)",
        "historical_spy_dd": -25.4,
        "historical_vix_peak": 36.5,
    },
    "Slow Bear (2007-09 extended)": {
        "description": "Extended bear market including full GFC + early recovery phase",
        "start": "2007-07-01",
        "end": "2010-06-30",
        "type": "Extended bear (36 months)",
        "historical_spy_dd": -56.8,
        "historical_vix_peak": 80.9,
    },
    "Flash Crash (Aug 2015)": {
        "description": "China devaluation flash crash: SPY -12% in 4 days, VIX spiked to 53, recovered in ~2 weeks",
        "start": "2015-08-10",
        "end": "2015-10-31",
        "type": "Flash crash + quick recovery (~3 months window)",
        "historical_spy_dd": -12.4,
        "historical_vix_peak": 53.3,
    },
}

# ─────────────────────────────────────────────────────────────
# 5. Run analysis for each scenario
# ─────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("CRISIS SCENARIO ANALYSIS")
print("=" * 70)

all_results = {}
strategy_names = {
    "BH_SPY": "Buy & Hold SPY",
    "12VIX_SPY": "12/VIX (SPY)",
    "5050_12VIX": "50/50 SPY/GLD + 12/VIX",
    "Piecewise": "Piecewise Conservative",
}

for scenario_name, info in SCENARIOS.items():
    print(f"\n{'─' * 60}")
    print(f"Scenario: {scenario_name}")
    print(f"  {info['description']}")
    print(f"  Period: {info['start']} to {info['end']}")
    print(f"  Type: {info['type']}")
    print(f"{'─' * 60}")

    nav_df = simulate_strategies(
        info["start"], info["end"],
        spy, gld, vix, spy_ret, gld_ret
    )

    if nav_df is None:
        print("  [SKIPPED] Insufficient data for this period")
        continue

    metrics = compute_crisis_metrics(nav_df, scenario_name)

    print(f"\n  If a {scenario_name} happens to your $100,000 portfolio:")
    print(f"  {'Strategy':<30} {'Max DD':>10} {'$ Loss':>12} {'UW Days':>10} {'Recovery':>10} {'Final $':>10}")
    print(f"  {'─' * 82}")

    for strat_key, strat_name in strategy_names.items():
        m = metrics[strat_key]
        dd_str = f"{m['max_drawdown_pct']:.1f}%"
        loss_str = f"${m['peak_to_trough_dollar']:,.0f}"
        uw_str = f"{m['underwater_span_calendar_days']}d"
        rec_str = f"{m['recovery_from_trough_days']}d" if m['recovery_from_trough_days'] is not None else "N/R"
        final_str = f"${m['final_value']:,.0f}"
        print(f"  {strat_name:<30} {dd_str:>10} {loss_str:>12} {uw_str:>10} {rec_str:>10} {final_str:>10}")

    # VIX behavior
    vix_slice = vix.loc[info["start"]:info["end"]]
    if len(vix_slice) > 0:
        print(f"\n  VIX during crisis: avg={vix_slice.mean():.1f}, peak={vix_slice.max():.1f}, "
              f"days above 25={int((vix_slice > 25).sum())}, days above 30={int((vix_slice > 30).sum())}")

    # Strategy behavior narrative
    print(f"\n  What each strategy DOES during this crisis:")
    for strat_key, strat_name in strategy_names.items():
        m = metrics[strat_key]
        if strat_key == "BH_SPY":
            print(f"    {strat_name}: Fully exposed. Takes full hit ({m['max_drawdown_pct']:.1f}%).")
        elif strat_key == "12VIX_SPY":
            # Show weight range during crisis
            vix_in_crisis = vix.loc[info["start"]:info["end"]]
            if len(vix_in_crisis) > 0:
                w_min = min(12.0 / vix_in_crisis.max(), 1.0)
                w_max = min(12.0 / vix_in_crisis.min(), 1.0)
                print(f"    {strat_name}: Equity weight ranges {w_min*100:.0f}%-{w_max*100:.0f}%. "
                      f"Automatically reduces exposure as VIX rises. DD: {m['max_drawdown_pct']:.1f}%.")
            else:
                print(f"    {strat_name}: DD {m['max_drawdown_pct']:.1f}%.")
        elif strat_key == "5050_12VIX":
            print(f"    {strat_name}: Diversified + VIX-scaled. GLD provides partial hedge. DD: {m['max_drawdown_pct']:.1f}%.")
        elif strat_key == "Piecewise":
            vix_in_crisis = vix.loc[info["start"]:info["end"]]
            if len(vix_in_crisis) > 0:
                days_full_cash = int((vix_in_crisis > 20).sum())
                days_full_invest = int((vix_in_crisis < 12).sum())
                days_rampdown = len(vix_in_crisis) - days_full_cash - days_full_invest
                print(f"    {strat_name}: Full cash {days_full_cash} days, ramp-down {days_rampdown} days, "
                      f"fully invested {days_full_invest} days. DD: {m['max_drawdown_pct']:.1f}%.")

    # Store results
    all_results[scenario_name] = {
        "info": info,
        "metrics": metrics,
        "trading_days": len(nav_df),
    }

# ─────────────────────────────────────────────────────────────
# 6. Stress Test Summary: Which strategy survives ALL 5 best?
# ─────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("STRESS TEST SUMMARY: WHICH STRATEGY SURVIVES ALL 5 SCENARIOS BEST?")
print("=" * 70)

# Aggregate metrics across all scenarios
summary = {}
for strat_key, strat_name in strategy_names.items():
    dds = []
    losses = []
    uw_days = []
    finals = []
    total_rets = []

    for scenario_name, result in all_results.items():
        m = result["metrics"][strat_key]
        dds.append(m["max_drawdown_pct"])
        losses.append(m["peak_to_trough_dollar"])
        if m["underwater_span_calendar_days"] is not None:
            uw_days.append(m["underwater_span_calendar_days"])
        finals.append(m["final_value"])
        total_rets.append(m["total_return_pct"])

    summary[strat_key] = {
        "name": strat_name,
        "worst_dd_pct": min(dds),
        "avg_dd_pct": round(np.mean(dds), 2),
        "avg_dollar_loss": round(np.mean(losses), 0),
        "worst_dollar_loss": min(losses),
        "avg_underwater_days": round(np.mean(uw_days), 0) if uw_days else None,
        "max_underwater_days": max(uw_days) if uw_days else None,
        "avg_total_return_pct": round(np.mean(total_rets), 2),
        "scenarios_positive": sum(1 for r in total_rets if r > 0),
        "all_dd": dds,
        "all_returns": total_rets,
    }

print(f"\n  {'Strategy':<30} {'Worst DD':>10} {'Avg DD':>10} {'Worst $ Loss':>14} {'Avg UW Days':>12} {'Scenarios +':>12}")
print(f"  {'─' * 88}")

# Rank by average drawdown (less negative = better)
ranked = sorted(summary.items(), key=lambda x: x[1]["avg_dd_pct"], reverse=True)

for rank, (strat_key, s) in enumerate(ranked, 1):
    medal = ["1st", "2nd", "3rd", "4th"][rank - 1]
    print(f"  {medal} {s['name']:<26} {s['worst_dd_pct']:.1f}% {s['avg_dd_pct']:.1f}%"
          f"  ${s['worst_dollar_loss']:>12,.0f}"
          f"  {s['avg_underwater_days']:>10.0f}d"
          f"  {s['scenarios_positive']}/5")

print(f"\n  Ranking criteria: Average max drawdown across all 5 crisis scenarios")
print(f"  (Lower absolute drawdown = better crisis protection)")

# Detailed per-scenario table
print(f"\n  {'Scenario':<30}", end="")
for strat_key, strat_name in strategy_names.items():
    short = strat_name.split("(")[0].strip()[:12]
    print(f" {short:>14}", end="")
print()
print(f"  {'─' * 86}")

for scenario_name, result in all_results.items():
    short_name = scenario_name[:28]
    print(f"  {short_name:<30}", end="")
    for strat_key in strategy_names:
        m = result["metrics"][strat_key]
        print(f" {m['max_drawdown_pct']:>12.1f}%", end="")
    print()

# ─────────────────────────────────────────────────────────────
# 7. Key Insights
# ─────────────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("KEY INSIGHTS")
print("=" * 70)

# Find best and worst strategies
best_strat = ranked[0]
worst_strat = ranked[-1]

print(f"""
1. BEST CRISIS PROTECTION: {best_strat[1]['name']}
   - Average drawdown across 5 crises: {best_strat[1]['avg_dd_pct']:.1f}%
   - Worst single scenario: {best_strat[1]['worst_dd_pct']:.1f}%
   - Positive return in {best_strat[1]['scenarios_positive']}/5 scenarios

2. WORST HIT (benchmark): {worst_strat[1]['name']}
   - Average drawdown: {worst_strat[1]['avg_dd_pct']:.1f}%
   - Worst single scenario: {worst_strat[1]['worst_dd_pct']:.1f}%

3. PROTECTION RATIO (avg DD best / avg DD worst):
   {abs(best_strat[1]['avg_dd_pct'] / worst_strat[1]['avg_dd_pct']) * 100:.0f}% less drawdown

4. THE TRADE-OFF:
   - More protection = less upside in V-recoveries (COVID, Flash Crash)
   - Piecewise goes to 100% cash when VIX>20 — great for crashes, misses rebounds
   - 12/VIX is the middle ground: reduces exposure but never goes to zero

5. DOLLAR IMPACT on $100K:
   """)

for strat_key, strat_name in strategy_names.items():
    s = summary[strat_key]
    print(f"   {strat_name}: worst loss ${abs(s['worst_dollar_loss']):,.0f}, "
          f"avg loss ${abs(s['avg_dollar_loss']):,.0f}")

# ─────────────────────────────────────────────────────────────
# 8. Save results
# ─────────────────────────────────────────────────────────────

output = {
    "experiment_id": "K674",
    "title": "What-If Crisis Scenarios: Strategy Performance During 5 Historical Crises",
    "description": "Empirical analysis using ACTUAL historical data from 5 crisis episodes "
                   "(GFC, COVID, Rate Shock, Extended Bear, Flash Crash) to show portfolio "
                   "impact under 4 VT strategies on a $100K portfolio.",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{START} to {END}",
    "sample_days": len(common_idx),
    "methodology": "Historical simulation using actual daily returns and VIX levels. "
                   "Strategy weights computed daily using previous day's VIX. "
                   "Cash earns 0% (conservative assumption).",
    "strategies": {
        "BH_SPY": "Buy & Hold SPY (100% equity, no risk management)",
        "12VIX_SPY": "12/VIX SPY: equity weight = min(12/VIX, 1.0), rest in cash",
        "5050_12VIX": "50/50 SPY/GLD with 12/VIX total weight sizing",
        "Piecewise": "Piecewise Conservative: 50/50 SPY/GLD, VIX<12 full, 12-20 ramp, >20 cash",
    },
    "scenarios": {},
    "stress_test_summary": {},
    "ranking": [],
    "key_insights": {},
    "references": [
        "Moreira & Muir (2017), Volatility-Managed Portfolios, Journal of Finance",
        "Fleming et al. (2001), Economic value of volatility timing, JFE",
        "VolPred K569/K574: Piecewise conservative strategy design",
        "VolPred K552: Fear DCA strategy",
    ],
    "limitations": [
        "Cash return assumed 0% (conservative; actual SHY yield would improve VT strategies)",
        "No transaction costs (monthly rebalancing ~5-10 bps/year impact)",
        "VIX used as-is from previous day close (no intraday adjustment)",
        "GLD data starts Nov 2004, so pre-2004 analysis not possible",
        "Past crises may not represent future crisis dynamics",
        "Single-path analysis (no bootstrap confidence intervals)",
    ],
    "timestamp": datetime.now().isoformat(),
}

# Per-scenario results
for scenario_name, result in all_results.items():
    output["scenarios"][scenario_name] = {
        "info": result["info"],
        "trading_days": result["trading_days"],
        "metrics": result["metrics"],
    }

# Summary
for strat_key, s in summary.items():
    output["stress_test_summary"][strat_key] = {
        "name": s["name"],
        "worst_dd_pct": s["worst_dd_pct"],
        "avg_dd_pct": s["avg_dd_pct"],
        "avg_dollar_loss": s["avg_dollar_loss"],
        "worst_dollar_loss": s["worst_dollar_loss"],
        "avg_underwater_span_days": s["avg_underwater_days"],
        "max_underwater_span_days": s["max_underwater_days"],
        "avg_total_return_pct": s["avg_total_return_pct"],
        "scenarios_positive": s["scenarios_positive"],
    }

# Ranking
for rank, (strat_key, s) in enumerate(ranked, 1):
    output["ranking"].append({
        "rank": rank,
        "strategy": strat_key,
        "name": s["name"],
        "avg_dd_pct": s["avg_dd_pct"],
        "worst_dd_pct": s["worst_dd_pct"],
    })

# Key insights
output["key_insights"] = {
    "best_protection": {
        "strategy": ranked[0][1]["name"],
        "avg_dd_pct": ranked[0][1]["avg_dd_pct"],
        "worst_dd_pct": ranked[0][1]["worst_dd_pct"],
    },
    "worst_hit": {
        "strategy": ranked[-1][1]["name"],
        "avg_dd_pct": ranked[-1][1]["avg_dd_pct"],
        "worst_dd_pct": ranked[-1][1]["worst_dd_pct"],
    },
    "protection_ratio_pct": round(
        abs(ranked[0][1]["avg_dd_pct"] / ranked[-1][1]["avg_dd_pct"]) * 100, 1
    ),
    "dollar_impact": {
        s["name"]: {
            "worst_loss": s["worst_dollar_loss"],
            "avg_loss": s["avg_dollar_loss"],
        }
        for s in summary.values()
    },
}

# Save
out_path = Path(__file__).parent / "k674_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to: {out_path}")
print("Done!")
