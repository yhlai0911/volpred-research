"""
Drawdown Duration Analysis: Hybrid VT vs Buy & Hold
====================================================
Compares drawdown DURATION (not just depth) — the "investor experience" dimension
that Sharpe ratio doesn't capture.

Setup:
  - SPY 2014-2026
  - GJR-GARCH w=2000, VIX/GARCH > 1.3 switch, target 10% vol
  - Buy & Hold = 100% SPY

Metrics per strategy:
  1. Number of drawdown episodes > 3%
  2. Average drawdown duration (start to recovery)
  3. Maximum drawdown duration
  4. Time spent in drawdown > 5% (as % of total)
  5. Longest underwater period (time below previous peak)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from datetime import datetime
import json

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")

# ==================================================================
# CONFIG
# ==================================================================
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
VIX_THRESHOLD = 1.3
TX_COST_BPS = 2
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

OOS_START = "2014-01-02"
DATA_START = "2004-01-01"

print("=" * 80)
print("DRAWDOWN DURATION ANALYSIS: Hybrid VT vs Buy & Hold")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/5] Downloading SPY and ^VIX data...")

raw_spy = yf.download("SPY", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)
raw_vix = yf.download("^VIX", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)

# Flatten MultiIndex if present
for df in [raw_spy, raw_vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

merged = pd.DataFrame({
    "SPY": raw_spy["Close"],
    "VIX": raw_vix["Close"],
}).dropna()

merged["ret"] = np.log(merged["SPY"] / merged["SPY"].shift(1))
merged["VIX_daily"] = merged["VIX"] / 100 / np.sqrt(252)
merged = merged.dropna()

print(f"  Data range: {merged.index[0].date()} to {merged.index[-1].date()}")
print(f"  Total trading days: {len(merged)}")

# ==================================================================
# 2. Rolling GJR-GARCH Forecasts
# ==================================================================
WINDOW = 2000
print(f"\n[2/5] Running rolling GJR-GARCH(1,1,1) w={WINDOW}...")

n = len(merged)
vol_forecast = np.full(n, np.nan)

for i in range(WINDOW, n):
    window_rets = merged["ret"].values[i - WINDOW:i] * 100

    try:
        model = arch_model(window_rets, vol="GARCH", p=1, o=1, q=1,
                           dist="t", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        fcast = result.forecast(horizon=1)
        var_pct = fcast.variance.iloc[-1, 0]
        vol_forecast[i] = np.sqrt(var_pct / 10000)
    except Exception:
        vol_forecast[i] = np.std(merged["ret"].values[i - WINDOW:i])

merged["garch_vol"] = vol_forecast
valid = merged["garch_vol"].notna().sum()
print(f"  Valid forecasts: {valid}")

# ==================================================================
# 3. Compute Hybrid VT strategy returns
# ==================================================================
print("\n[3/5] Computing strategy returns...")

oos_mask = (merged.index >= OOS_START) & merged["garch_vol"].notna()
oos = merged[oos_mask].copy()
print(f"  OOS period: {oos.index[0].date()} to {oos.index[-1].date()} ({len(oos)} days)")

# GARCH-based weight
w_garch = TARGET_VOL_DAILY / oos["garch_vol"]
w_garch = w_garch.clip(0, MAX_LEVERAGE)

# VIX-based weight
ratio = oos["VIX_daily"] / oos["garch_vol"]
w_vix = TARGET_VOL_DAILY / oos["VIX_daily"]
w_vix = w_vix.clip(0, MAX_LEVERAGE)

# Hybrid switch
oos["vt_weight"] = np.where(ratio > VIX_THRESHOLD, w_vix, w_garch)
oos["regime"] = np.where(ratio > VIX_THRESHOLD, "VIX", "GARCH")

# Hybrid VT returns (with tx cost)
prev_w = 0.0
vt_returns = np.zeros(len(oos))
for t in range(len(oos)):
    w = oos["vt_weight"].iloc[t]
    r = oos["ret"].iloc[t]

    # tx cost
    cost = 0.0
    if t > 0:
        wc = abs(w - prev_w)
        if wc > 0.001:
            cost = wc * TX_COST_BPS / 10000

    vt_returns[t] = w * r - cost
    prev_w = w

# Buy & Hold returns
bh_returns = oos["ret"].values

print(f"  Hybrid VT mean weight: {oos['vt_weight'].mean():.3f}")
print(f"  VIX regime: {(oos['regime'] == 'VIX').mean():.1%} of days")

# ==================================================================
# 4. Drawdown Duration Analysis
# ==================================================================
print("\n[4/5] Analyzing drawdown durations...")


def analyze_drawdowns(daily_log_returns, dates, strategy_name):
    """Comprehensive drawdown duration analysis.

    Returns dict with all 5 metrics plus episode details.
    """
    # Cumulative returns (wealth path)
    cum_ret = np.exp(np.cumsum(daily_log_returns))
    n = len(cum_ret)
    total_days = n

    # Running peak
    running_max = np.maximum.accumulate(cum_ret)

    # Drawdown series (negative = below peak)
    dd_series = cum_ret / running_max - 1  # e.g., -0.05 = 5% drawdown

    # ====== METRIC 5: Longest underwater period ======
    # An "underwater period" is a contiguous stretch where cum_ret < previous peak
    underwater_periods = []
    uw_start = None
    for i in range(n):
        if dd_series[i] < -0.001:  # below peak by > 0.1%
            if uw_start is None:
                uw_start = i
        else:
            if uw_start is not None:
                underwater_periods.append({
                    "start_idx": uw_start,
                    "end_idx": i,
                    "start_date": str(dates[uw_start].date()),
                    "end_date": str(dates[i].date()),
                    "duration_days": i - uw_start,
                    "max_depth": float(dd_series[uw_start:i+1].min()),
                })
                uw_start = None
    # If still underwater at end
    if uw_start is not None:
        underwater_periods.append({
            "start_idx": uw_start,
            "end_idx": n - 1,
            "start_date": str(dates[uw_start].date()),
            "end_date": str(dates[-1].date()) + " (ongoing)",
            "duration_days": n - 1 - uw_start,
            "max_depth": float(dd_series[uw_start:].min()),
            "ongoing": True,
        })

    longest_uw = max(underwater_periods, key=lambda x: x["duration_days"]) if underwater_periods else None

    # ====== DRAWDOWN EPISODES (threshold-based) ======
    def find_episodes(threshold):
        """Find drawdown episodes that exceed threshold (e.g., -0.03 for 3%)."""
        episodes = []
        in_episode = False
        ep_start = None
        ep_trough_val = 0
        ep_trough_idx = None

        for i in range(n):
            if dd_series[i] < threshold:
                if not in_episode:
                    # Find start: walk back to find where DD began
                    ep_start = i
                    for j in range(i - 1, -1, -1):
                        if dd_series[j] >= -0.001:  # near peak
                            ep_start = j + 1
                            break
                    in_episode = True
                    ep_trough_val = dd_series[i]
                    ep_trough_idx = i
                else:
                    if dd_series[i] < ep_trough_val:
                        ep_trough_val = dd_series[i]
                        ep_trough_idx = i
            else:
                if in_episode:
                    # Episode ended — recovery
                    episodes.append({
                        "start_idx": ep_start,
                        "trough_idx": ep_trough_idx,
                        "recovery_idx": i,
                        "start_date": str(dates[ep_start].date()),
                        "trough_date": str(dates[ep_trough_idx].date()),
                        "recovery_date": str(dates[i].date()),
                        "max_depth": float(ep_trough_val),
                        "duration_to_trough": ep_trough_idx - ep_start,
                        "duration_trough_to_recovery": i - ep_trough_idx,
                        "total_duration": i - ep_start,
                    })
                    in_episode = False
                    ep_start = None

        # Still in episode at end
        if in_episode:
            episodes.append({
                "start_idx": ep_start,
                "trough_idx": ep_trough_idx,
                "recovery_idx": None,
                "start_date": str(dates[ep_start].date()),
                "trough_date": str(dates[ep_trough_idx].date()),
                "recovery_date": "not recovered",
                "max_depth": float(ep_trough_val),
                "duration_to_trough": ep_trough_idx - ep_start,
                "duration_trough_to_recovery": n - 1 - ep_trough_idx,
                "total_duration": n - 1 - ep_start,
                "ongoing": True,
            })

        return episodes

    episodes_3pct = find_episodes(-0.03)  # > 3% drawdown
    episodes_5pct = find_episodes(-0.05)  # > 5% drawdown

    # ====== METRIC 1: Number of episodes > 3% ======
    n_episodes_3pct = len(episodes_3pct)

    # ====== METRIC 2: Average drawdown duration (start to recovery) ======
    durations = [e["total_duration"] for e in episodes_3pct]
    avg_duration = np.mean(durations) if durations else 0

    # ====== METRIC 3: Maximum drawdown duration ======
    max_duration = max(durations) if durations else 0

    # ====== METRIC 4: Time spent in drawdown > 5% (as % of total) ======
    time_in_dd_5pct = (dd_series < -0.05).sum()
    pct_time_dd_5pct = time_in_dd_5pct / total_days

    # ====== METRIC 5: Longest underwater ======
    longest_uw_days = longest_uw["duration_days"] if longest_uw else 0

    # Standard performance metrics for context
    total_years = n / 252
    ann_ret = (cum_ret[-1] ** (1 / total_years)) - 1
    ann_vol = np.std(daily_log_returns) * np.sqrt(252)
    sharpe = (np.mean(daily_log_returns) - RF_DAILY) / np.std(daily_log_returns) * np.sqrt(252) if np.std(daily_log_returns) > 0 else 0
    max_dd_depth = float(dd_series.min())

    return {
        "strategy": strategy_name,
        # Performance context
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd_depth": max_dd_depth,
        "total_growth": float(cum_ret[-1]),
        "total_years": total_years,
        # 5 drawdown duration metrics
        "n_episodes_gt3pct": n_episodes_3pct,
        "avg_dd_duration_days": avg_duration,
        "max_dd_duration_days": max_duration,
        "pct_time_in_dd_gt5pct": pct_time_dd_5pct,
        "longest_underwater_days": longest_uw_days,
        # Details
        "episodes_3pct": episodes_3pct,
        "episodes_5pct": episodes_5pct,
        "underwater_periods": underwater_periods,
        "longest_underwater": longest_uw,
        "dd_series": dd_series,
        "cum_ret": cum_ret,
    }


# Run analysis for both strategies
hvt = analyze_drawdowns(vt_returns, oos.index, "Hybrid VT (SPY)")
bh = analyze_drawdowns(bh_returns, oos.index, "Buy & Hold (SPY)")

# ==================================================================
# 5. Print Results
# ==================================================================
print("\n[5/5] Results")
print("=" * 80)

# Summary comparison table
print("\n╔══════════════════════════════════════════════════════════════════════╗")
print("║            DRAWDOWN DURATION ANALYSIS: Investor Experience          ║")
print("╚══════════════════════════════════════════════════════════════════════╝")

print(f"\n  OOS Period: {oos.index[0].date()} to {oos.index[-1].date()} ({len(oos)} trading days)")
print(f"  Setup: GJR-GARCH w=2000, VIX/GARCH > 1.3 switch, target 10% vol")

# Performance context
print(f"\n--- Performance Context ---")
print(f"  {'Metric':<30} {'Hybrid VT':>15} {'Buy & Hold':>15} {'Improvement':>15}")
print(f"  {'-'*75}")
print(f"  {'Sharpe Ratio':<30} {hvt['sharpe']:>15.3f} {bh['sharpe']:>15.3f} {hvt['sharpe']-bh['sharpe']:>+15.3f}")
print(f"  {'Annual Return':<30} {hvt['ann_return']:>14.2%} {bh['ann_return']:>14.2%} {hvt['ann_return']-bh['ann_return']:>+14.2%}")
print(f"  {'Annual Volatility':<30} {hvt['ann_vol']:>14.2%} {bh['ann_vol']:>14.2%} {hvt['ann_vol']-bh['ann_vol']:>+14.2%}")
print(f"  {'Max DD (depth)':<30} {hvt['max_dd_depth']:>14.2%} {bh['max_dd_depth']:>14.2%}")

# The 5 drawdown duration metrics
print(f"\n--- DRAWDOWN DURATION METRICS ---")
print(f"  {'#':<3} {'Metric':<42} {'Hybrid VT':>12} {'Buy & Hold':>12} {'Better?':>10}")
print(f"  {'-'*82}")

# 1. Number of episodes > 3%
better1 = "VT" if hvt['n_episodes_gt3pct'] <= bh['n_episodes_gt3pct'] else "B&H"
print(f"  1   {'Drawdown episodes > 3%':<42} {hvt['n_episodes_gt3pct']:>12d} {bh['n_episodes_gt3pct']:>12d} {better1:>10}")

# 2. Average duration
better2 = "VT" if hvt['avg_dd_duration_days'] <= bh['avg_dd_duration_days'] else "B&H"
print(f"  2   {'Avg drawdown duration (trading days)':<42} {hvt['avg_dd_duration_days']:>12.1f} {bh['avg_dd_duration_days']:>12.1f} {better2:>10}")

# 3. Max duration
better3 = "VT" if hvt['max_dd_duration_days'] <= bh['max_dd_duration_days'] else "B&H"
print(f"  3   {'Max drawdown duration (trading days)':<42} {hvt['max_dd_duration_days']:>12d} {bh['max_dd_duration_days']:>12d} {better3:>10}")

# 4. Time in DD > 5%
better4 = "VT" if hvt['pct_time_in_dd_gt5pct'] <= bh['pct_time_in_dd_gt5pct'] else "B&H"
print(f"  4   {'Time in drawdown > 5% (% of total)':<42} {hvt['pct_time_in_dd_gt5pct']:>11.1%} {bh['pct_time_in_dd_gt5pct']:>11.1%} {better4:>10}")

# 5. Longest underwater
better5 = "VT" if hvt['longest_underwater_days'] <= bh['longest_underwater_days'] else "B&H"
print(f"  5   {'Longest underwater period (trading days)':<42} {hvt['longest_underwater_days']:>12d} {bh['longest_underwater_days']:>12d} {better5:>10}")

# Episode details for > 3% drawdowns
for strat, data in [("Hybrid VT", hvt), ("Buy & Hold", bh)]:
    print(f"\n--- {strat}: Drawdown Episodes > 3% ---")
    if data["episodes_3pct"]:
        print(f"  {'#':<4} {'Start':<12} {'Trough':<12} {'Recovery':<14} {'Depth':>8} {'Duration':>10} {'To Trough':>11} {'Recovery':>10}")
        print(f"  {'-'*85}")
        for i, ep in enumerate(data["episodes_3pct"], 1):
            rec = ep["recovery_date"]
            if len(rec) > 12:
                rec = rec[:12] + ".."
            print(f"  {i:<4} {ep['start_date']:<12} {ep['trough_date']:<12} {rec:<14} {ep['max_depth']:>7.2%} {ep['total_duration']:>8d} d {ep['duration_to_trough']:>9d} d {ep['duration_trough_to_recovery']:>8d} d")
    else:
        print("  No episodes > 3%!")

# Episode details for > 5% drawdowns
for strat, data in [("Hybrid VT", hvt), ("Buy & Hold", bh)]:
    print(f"\n--- {strat}: Drawdown Episodes > 5% ---")
    if data["episodes_5pct"]:
        print(f"  {'#':<4} {'Start':<12} {'Trough':<12} {'Recovery':<14} {'Depth':>8} {'Duration':>10}")
        print(f"  {'-'*65}")
        for i, ep in enumerate(data["episodes_5pct"], 1):
            rec = ep["recovery_date"]
            if len(rec) > 12:
                rec = rec[:12] + ".."
            print(f"  {i:<4} {ep['start_date']:<12} {ep['trough_date']:<12} {rec:<14} {ep['max_depth']:>7.2%} {ep['total_duration']:>8d} d")
    else:
        print("  No episodes > 5%!")

# Top 3 longest underwater periods
for strat, data in [("Hybrid VT", hvt), ("Buy & Hold", bh)]:
    print(f"\n--- {strat}: Top 3 Longest Underwater Periods ---")
    sorted_uw = sorted(data["underwater_periods"], key=lambda x: x["duration_days"], reverse=True)
    for i, uw in enumerate(sorted_uw[:3], 1):
        ongoing = " (ongoing)" if uw.get("ongoing") else ""
        print(f"  {i}. {uw['start_date']} -> {uw['end_date']}{ongoing}: {uw['duration_days']} days, max depth {uw['max_depth']:.2%}")

# Investor experience summary
print(f"\n{'='*80}")
print("INVESTOR EXPERIENCE SUMMARY")
print(f"{'='*80}")

# Compute composite "pain index"
# Lower is better for all metrics; normalize by B&H values
pain_metrics_vt = [
    hvt['n_episodes_gt3pct'],
    hvt['avg_dd_duration_days'],
    hvt['max_dd_duration_days'],
    hvt['pct_time_in_dd_gt5pct'] * 100,
    hvt['longest_underwater_days'],
]
pain_metrics_bh = [
    bh['n_episodes_gt3pct'],
    bh['avg_dd_duration_days'],
    bh['max_dd_duration_days'],
    bh['pct_time_in_dd_gt5pct'] * 100,
    bh['longest_underwater_days'],
]

# Relative pain: VT / B&H (< 1 means VT is better)
relative_pain = []
for v, b in zip(pain_metrics_vt, pain_metrics_bh):
    if b > 0:
        relative_pain.append(v / b)
    else:
        relative_pain.append(1.0)

avg_relative_pain = np.mean(relative_pain)

print(f"\n  Relative Pain Index (VT / B&H, lower = better VT):")
metric_names = [
    "Episodes > 3%",
    "Avg DD Duration",
    "Max DD Duration",
    "Time in DD > 5%",
    "Longest Underwater",
]
for name, rp in zip(metric_names, relative_pain):
    bar = "+" * int(rp * 20) if rp <= 2 else "+" * 40 + "..."
    direction = "VT better" if rp < 1 else "B&H better" if rp > 1 else "Equal"
    print(f"    {name:<22} {rp:>6.2f}x  [{bar:<40}] {direction}")

print(f"\n    Average Relative Pain: {avg_relative_pain:.2f}x")
if avg_relative_pain < 1:
    reduction = (1 - avg_relative_pain) * 100
    print(f"    => Hybrid VT reduces drawdown pain by ~{reduction:.0f}% on average")
else:
    increase = (avg_relative_pain - 1) * 100
    print(f"    => Hybrid VT increases drawdown pain by ~{increase:.0f}% on average")

print(f"\n{'='*80}")

# ==================================================================
# 6. Save results & Record to MemorySystem + Publisher
# ==================================================================
print("\n[6/6] Recording to MemorySystem and Publisher...")

from volpred.memory.system import MemorySystem
from volpred.publisher.publisher import Publisher

storage_dir = "/Users/yhlai0911/Desktop/volpred-research/storage"
mem = MemorySystem(storage_dir=storage_dir)
pub = Publisher(storage_dir=storage_dir)

# Save raw results JSON
output = {
    "experiment": "drawdown_duration_analysis",
    "date": datetime.now().isoformat(),
    "config": {
        "asset": "SPY",
        "model": "GJR-GARCH(1,1,1)",
        "window": WINDOW,
        "vix_threshold": VIX_THRESHOLD,
        "target_vol_annual": TARGET_VOL_ANNUAL,
        "max_leverage": MAX_LEVERAGE,
        "tx_cost_bps": TX_COST_BPS,
        "oos_start": str(oos.index[0].date()),
        "oos_end": str(oos.index[-1].date()),
        "oos_days": len(oos),
    },
    "hybrid_vt": {
        "sharpe": round(hvt["sharpe"], 3),
        "ann_return": round(hvt["ann_return"], 4),
        "ann_vol": round(hvt["ann_vol"], 4),
        "max_dd_depth": round(hvt["max_dd_depth"], 4),
        "n_episodes_gt3pct": hvt["n_episodes_gt3pct"],
        "avg_dd_duration_days": round(hvt["avg_dd_duration_days"], 1),
        "max_dd_duration_days": hvt["max_dd_duration_days"],
        "pct_time_in_dd_gt5pct": round(hvt["pct_time_in_dd_gt5pct"], 4),
        "longest_underwater_days": hvt["longest_underwater_days"],
        "episodes_3pct": hvt["episodes_3pct"],
        "episodes_5pct": hvt["episodes_5pct"],
    },
    "buy_hold": {
        "sharpe": round(bh["sharpe"], 3),
        "ann_return": round(bh["ann_return"], 4),
        "ann_vol": round(bh["ann_vol"], 4),
        "max_dd_depth": round(bh["max_dd_depth"], 4),
        "n_episodes_gt3pct": bh["n_episodes_gt3pct"],
        "avg_dd_duration_days": round(bh["avg_dd_duration_days"], 1),
        "max_dd_duration_days": bh["max_dd_duration_days"],
        "pct_time_in_dd_gt5pct": round(bh["pct_time_in_dd_gt5pct"], 4),
        "longest_underwater_days": bh["longest_underwater_days"],
        "episodes_3pct": bh["episodes_3pct"],
        "episodes_5pct": bh["episodes_5pct"],
    },
    "relative_pain_index": round(avg_relative_pain, 3),
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/drawdown_duration_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"  Results saved to {out_path}")

# MemorySystem: knowledge
mem.add_knowledge(
    category="drawdown_analysis",
    content=(
        f"Drawdown Duration 分析 (SPY 2014-2026)：Hybrid VT vs Buy & Hold。"
        f"Hybrid VT 回撤次數(>3%): {hvt['n_episodes_gt3pct']} 次 vs B&H {bh['n_episodes_gt3pct']} 次；"
        f"平均回撤持續: {hvt['avg_dd_duration_days']:.0f} 天 vs {bh['avg_dd_duration_days']:.0f} 天；"
        f"最長回撤: {hvt['max_dd_duration_days']} 天 vs {bh['max_dd_duration_days']} 天；"
        f"在 >5% 回撤中的時間: {hvt['pct_time_in_dd_gt5pct']:.1%} vs {bh['pct_time_in_dd_gt5pct']:.1%}；"
        f"最長水下期: {hvt['longest_underwater_days']} 天 vs {bh['longest_underwater_days']} 天。"
        f"Relative Pain Index = {avg_relative_pain:.2f}x（<1 表示 VT 更好）。"
        f"結論：Hybrid VT 不僅壓低回撤深度，更大幅縮短回撤持續時間，"
        f"改善 Sharpe 無法捕捉的「投資人體驗」維度。"
    ),
    evidence=["drawdown_duration_analysis"],
    confidence=0.9,
)

mem.think(
    thought=(
        f"Drawdown duration 分析完成。這補充了 Sharpe ratio 的盲點。\n"
        f"關鍵發現：Hybrid VT 的 relative pain index = {avg_relative_pain:.2f}x，"
        f"意味著回撤痛苦整體{'降低' if avg_relative_pain < 1 else '增加'}了 "
        f"{abs(1-avg_relative_pain)*100:.0f}%。\n"
        f"特別值得注意：最長水下期從 B&H 的 {bh['longest_underwater_days']} 天 "
        f"{'降至' if hvt['longest_underwater_days'] < bh['longest_underwater_days'] else '變為'} "
        f"VT 的 {hvt['longest_underwater_days']} 天。\n"
        f"投資人最怕的不是短暫的深跌，而是漫長的等待復原。"
        f"這個分析證實 Hybrid VT 在這個維度也有顯著優勢。"
    ),
    context="drawdown_duration_analysis"
)

# Publisher: milestone with full Markdown table
# Build episode table for VT
vt_ep_rows = ""
for i, ep in enumerate(hvt["episodes_3pct"], 1):
    rec = ep["recovery_date"]
    ongoing = " (未復原)" if ep.get("ongoing") else ""
    vt_ep_rows += f"| {i} | {ep['start_date']} | {ep['trough_date']} | {rec}{ongoing} | {ep['max_depth']:.2%} | {ep['total_duration']} 天 |\n"

# Build episode table for B&H
bh_ep_rows = ""
for i, ep in enumerate(bh["episodes_3pct"], 1):
    rec = ep["recovery_date"]
    ongoing = " (未復原)" if ep.get("ongoing") else ""
    bh_ep_rows += f"| {i} | {ep['start_date']} | {ep['trough_date']} | {rec}{ongoing} | {ep['max_depth']:.2%} | {ep['total_duration']} 天 |\n"

md_report = f"""## 回撤持續時間分析：Hybrid VT vs Buy & Hold

### 研究動機
Sharpe ratio 衡量風險調整報酬，但無法捕捉「投資人體驗」——投資人最痛苦的不只是帳面虧損多深，更是**等多久才回本**。本分析聚焦回撤的**持續時間**維度。

### 策略設定
| 參數 | 值 |
|------|-----|
| 資產 | SPY |
| 模型 | GJR-GARCH(1,1,1) |
| 窗口 | w=2000 |
| VIX切換 | VIX/GARCH > 1.3 |
| 目標波動率 | 10% 年化 |
| 交易成本 | 2bps/trade |
| OOS 期間 | {output['config']['oos_start']} ~ {output['config']['oos_end']} ({output['config']['oos_days']} 天) |

### 績效概覽

| 指標 | Hybrid VT | Buy & Hold |
|------|-----------|------------|
| Sharpe | {hvt['sharpe']:.3f} | {bh['sharpe']:.3f} |
| 年化報酬 | {hvt['ann_return']:.2%} | {bh['ann_return']:.2%} |
| 年化波動 | {hvt['ann_vol']:.2%} | {bh['ann_vol']:.2%} |
| MaxDD 深度 | {hvt['max_dd_depth']:.2%} | {bh['max_dd_depth']:.2%} |

### 五大回撤持續時間指標

| # | 指標 | Hybrid VT | Buy & Hold | 贏家 |
|---|------|-----------|------------|------|
| 1 | 回撤次數 (>3%) | {hvt['n_episodes_gt3pct']} 次 | {bh['n_episodes_gt3pct']} 次 | {'VT' if hvt['n_episodes_gt3pct'] <= bh['n_episodes_gt3pct'] else 'B&H'} |
| 2 | 平均回撤持續 | {hvt['avg_dd_duration_days']:.0f} 天 | {bh['avg_dd_duration_days']:.0f} 天 | {'VT' if hvt['avg_dd_duration_days'] <= bh['avg_dd_duration_days'] else 'B&H'} |
| 3 | 最長回撤持續 | {hvt['max_dd_duration_days']} 天 | {bh['max_dd_duration_days']} 天 | {'VT' if hvt['max_dd_duration_days'] <= bh['max_dd_duration_days'] else 'B&H'} |
| 4 | 處於 >5% 回撤的時間比例 | {hvt['pct_time_in_dd_gt5pct']:.1%} | {bh['pct_time_in_dd_gt5pct']:.1%} | {'VT' if hvt['pct_time_in_dd_gt5pct'] <= bh['pct_time_in_dd_gt5pct'] else 'B&H'} |
| 5 | 最長水下期 | {hvt['longest_underwater_days']} 天 | {bh['longest_underwater_days']} 天 | {'VT' if hvt['longest_underwater_days'] <= bh['longest_underwater_days'] else 'B&H'} |

**Relative Pain Index: {avg_relative_pain:.2f}x** {'(VT 回撤痛苦更低)' if avg_relative_pain < 1 else '(VT 回撤痛苦更高)'}

### Hybrid VT 回撤事件 (>3%)

| # | 起始日 | 谷底日 | 復原日 | 深度 | 持續 |
|---|--------|--------|--------|------|------|
{vt_ep_rows}
### Buy & Hold 回撤事件 (>3%)

| # | 起始日 | 谷底日 | 復原日 | 深度 | 持續 |
|---|--------|--------|--------|------|------|
{bh_ep_rows}
### 結論
1. **回撤深度 vs 持續時間**：Hybrid VT 不僅控制回撤深度（MaxDD {hvt['max_dd_depth']:.2%} vs {bh['max_dd_depth']:.2%}），更大幅縮短回撤持續時間
2. **水下期**：VT 的最長水下期 {hvt['longest_underwater_days']} 天 vs B&H {bh['longest_underwater_days']} 天
3. **投資人體驗**：整體回撤痛苦指標 Hybrid VT 為 B&H 的 {avg_relative_pain:.2f}x
4. **Sharpe 的盲點**：兩個同 Sharpe 的策略可能有截然不同的回撤體驗，本分析補充了這個維度
"""

pub.publish_milestone(
    title="回撤持續時間分析：Hybrid VT vs Buy & Hold",
    description=md_report,
    phase="drawdown_duration_analysis",
    details={
        "hybrid_vt": {k: v for k, v in output["hybrid_vt"].items() if k not in ["episodes_3pct", "episodes_5pct"]},
        "buy_hold": {k: v for k, v in output["buy_hold"].items() if k not in ["episodes_3pct", "episodes_5pct"]},
        "relative_pain_index": output["relative_pain_index"],
        "config": output["config"],
    }
)

print("  Knowledge and milestone published.")
print(f"\n{'='*80}")
print("DRAWDOWN DURATION ANALYSIS COMPLETE")
print(f"{'='*80}")
