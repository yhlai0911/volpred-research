#!/usr/bin/env python3
"""
K655: Optimal Strategy by Investment Horizon
=============================================
[提出: Claude, 執行: Claude]

Motivation:
  K654 showed Piecewise Conservative wins in crisis-heavy short periods but
  loses over 20 years due to compounding drag. This raises the question:
  what is the BEST strategy for EACH investment horizon?

  A retiree with 3 years is very different from a 30-year-old with 30 years.
  This experiment answers: for each horizon h, which strategy maximises
  risk-adjusted returns while protecting against worst-case outcomes?

Strategies:
  1. 50/50 SPY/GLD + 12/VIX  (current recommended)
  2. Piecewise Conservative   (VIX < 12 → 100%, 12-20 → linear, > 20 → 0%)
  3. 80/20 SPY/GLD + 12/VIX  (K646 optimised)
  4. Buy-and-hold SPY         (passive benchmark)
  5. Buy-and-hold 60/40 SPY/GLD (classic diversification)

Method:
  For each horizon h in {1, 2, 3, 5, 7, 10, 15, 20} years:
    - Roll through ALL possible h-year windows (step = 21 trading days)
    - In each window, compute Sharpe, CAGR, MDD for every strategy
    - Aggregate: mean, median, worst-case, best-case, P(positive), P(beat SPY BH)

Data: yfinance SPY, GLD, ^VIX daily (2006-01-01 to 2026-03-27)

References:
  - K569: Piecewise VT validation
  - K574: Piecewise calibration
  - K640: Live performance audit
  - K645: GLD role analysis (80/20 optimal with 12/VIX)
  - K646: Cross-OOS 80/20 vs 50/50
  - K654: Why Piecewise dominates (short-term decomposition)
  - Copeland et al. (2009), "Lifecycle Investing", JAM
  - Campbell & Viceira (2002), "Strategic Asset Allocation", OUP
"""

import json
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────
# 1. DATA
# ─────────────────────────────────────────────────────────
print("=" * 70)
print("K655: Optimal Strategy by Investment Horizon")
print("=" * 70)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed")
    sys.exit(1)

START = "2006-01-01"
END = "2026-03-27"

print(f"\nDownloading SPY, GLD, ^VIX ({START} to {END})...")
tickers = ["SPY", "GLD", "^VIX"]
data = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)

# Extract close prices
spy_close = data["Close"]["SPY"].dropna()
gld_close = data["Close"]["GLD"].dropna()
vix_close = data["Close"]["^VIX"].dropna()

# Align dates
common_idx = spy_close.index.intersection(gld_close.index).intersection(vix_close.index)
spy_close = spy_close.loc[common_idx]
gld_close = gld_close.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"  Common trading days: {len(common_idx)}")
print(f"  Date range: {common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')}")

# Daily returns
spy_ret = spy_close.pct_change().dropna()
gld_ret = gld_close.pct_change().dropna()
vix = vix_close.loc[spy_ret.index]

print(f"  Return days: {len(spy_ret)}")
print(f"  VIX range: {vix.min():.2f} - {vix.max():.2f}")

# ─────────────────────────────────────────────────────────
# 2. STRATEGY RETURN SERIES
# ─────────────────────────────────────────────────────────
print("\n--- Computing strategy return series ---")

# Previous day VIX (no look-ahead bias)
vix_prev = vix.shift(1).dropna()
common = spy_ret.index.intersection(vix_prev.index)
spy_r = spy_ret.loc[common]
gld_r = gld_ret.loc[common]
vix_p = vix_prev.loc[common]


def piecewise_weight(vix_val, low=12.0, high=20.0):
    """Piecewise linear: 1.0 below low, 0.0 above high, linear between."""
    if vix_val < low:
        return 1.0
    elif vix_val <= high:
        return (high - vix_val) / (high - low)
    else:
        return 0.0


# Strategy 1: 50/50 SPY/GLD + 12/VIX
w_12vix = np.minimum(12.0 / vix_p.values, 1.0)
strat_5050_12vix = w_12vix * (0.5 * spy_r.values + 0.5 * gld_r.values)

# Strategy 2: Piecewise Conservative (50/50 base with piecewise weight)
pw_weights = vix_p.apply(piecewise_weight).values
strat_piecewise = pw_weights * (0.5 * spy_r.values + 0.5 * gld_r.values)

# Strategy 3: 80/20 SPY/GLD + 12/VIX
strat_8020_12vix = w_12vix * (0.8 * spy_r.values + 0.2 * gld_r.values)

# Strategy 4: Buy-and-hold SPY
strat_bh_spy = spy_r.values.copy()

# Strategy 5: Buy-and-hold 60/40 SPY/GLD
strat_bh_6040 = 0.6 * spy_r.values + 0.4 * gld_r.values

# Store as dict for easy iteration
strategies = {
    "50/50 + 12/VIX": strat_5050_12vix,
    "Piecewise Conservative": strat_piecewise,
    "80/20 + 12/VIX": strat_8020_12vix,
    "BH SPY": strat_bh_spy,
    "BH 60/40": strat_bh_6040,
}

dates = common  # date index

for name, rets in strategies.items():
    cum = (1 + rets).prod()
    ann_ret = cum ** (252 / len(rets)) - 1
    ann_vol = np.std(rets) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    print(f"  {name:25s}: CAGR={ann_ret:.4f}, Vol={ann_vol:.4f}, Sharpe={sharpe:.2f}")

# ─────────────────────────────────────────────────────────
# 3. ROLLING WINDOW ANALYSIS
# ─────────────────────────────────────────────────────────
HORIZONS_YEARS = [1, 2, 3, 5, 7, 10, 15, 20]
STEP_DAYS = 21  # monthly step
TRADING_DAYS_PER_YEAR = 252
RF_DAILY = (1 + 0.02) ** (1 / 252) - 1  # 2% risk-free rate


def compute_metrics(returns):
    """Compute Sharpe, CAGR, MDD for a return series."""
    n = len(returns)
    if n < 20:
        return None

    # CAGR
    cum = (1 + returns).prod()
    years = n / TRADING_DAYS_PER_YEAR
    cagr = cum ** (1 / years) - 1 if years > 0 else 0.0

    # Annualised volatility
    ann_vol = np.std(returns) * np.sqrt(TRADING_DAYS_PER_YEAR)

    # Sharpe (excess over risk-free)
    ann_ret = cagr
    sharpe = (ann_ret - 0.02) / ann_vol if ann_vol > 0 else 0.0

    # Maximum drawdown
    cumulative = (1 + returns).cumprod()
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    mdd = np.min(drawdowns)

    return {"sharpe": sharpe, "cagr": cagr, "mdd": mdd, "ann_vol": ann_vol}


print("\n" + "=" * 70)
print("Rolling Window Analysis by Horizon")
print("=" * 70)

all_results = {}
horizon_recommendations = {}

for h in HORIZONS_YEARS:
    window_days = h * TRADING_DAYS_PER_YEAR
    total_days = len(dates)

    if window_days > total_days:
        print(f"\n  Horizon {h}yr: window ({window_days}d) > data ({total_days}d), skipping")
        continue

    # Collect metrics for all windows
    strat_metrics = {name: [] for name in strategies}
    n_windows = 0

    for start_idx in range(0, total_days - window_days + 1, STEP_DAYS):
        end_idx = start_idx + window_days
        n_windows += 1

        for name, full_rets in strategies.items():
            window_rets = full_rets[start_idx:end_idx]
            m = compute_metrics(window_rets)
            if m is not None:
                strat_metrics[name].append(m)

    print(f"\n  Horizon {h}yr ({window_days}d): {n_windows} rolling windows")
    print(f"  {'Strategy':25s} | {'Mean Sh':>8s} {'Med Sh':>8s} {'Worst Sh':>8s} | "
          f"{'Mean CAGR':>10s} {'Med CAGR':>10s} {'Worst CAGR':>11s} | "
          f"{'Mean MDD':>9s} {'Worst MDD':>10s} | "
          f"{'P(>0)':>6s} {'P(>SPY)':>8s}")
    print("  " + "-" * 135)

    horizon_data = {}
    bh_spy_cagrs = [m["cagr"] for m in strat_metrics["BH SPY"]]

    for name in strategies:
        metrics_list = strat_metrics[name]
        if not metrics_list:
            continue

        sharpes = [m["sharpe"] for m in metrics_list]
        cagrs = [m["cagr"] for m in metrics_list]
        mdds = [m["mdd"] for m in metrics_list]
        vols = [m["ann_vol"] for m in metrics_list]

        # P(positive return)
        p_positive = sum(1 for c in cagrs if c > 0) / len(cagrs)

        # P(beat SPY BH)
        if name == "BH SPY":
            p_beat_spy = 1.0  # trivially
        else:
            p_beat_spy = sum(1 for c, s in zip(cagrs, bh_spy_cagrs) if c > s) / len(cagrs)

        horizon_data[name] = {
            "mean_sharpe": float(np.mean(sharpes)),
            "median_sharpe": float(np.median(sharpes)),
            "worst_sharpe": float(np.min(sharpes)),
            "best_sharpe": float(np.max(sharpes)),
            "mean_cagr": float(np.mean(cagrs)),
            "median_cagr": float(np.median(cagrs)),
            "worst_cagr": float(np.min(cagrs)),
            "best_cagr": float(np.max(cagrs)),
            "mean_mdd": float(np.mean(mdds)),
            "worst_mdd": float(np.min(mdds)),
            "mean_vol": float(np.mean(vols)),
            "p_positive": float(p_positive),
            "p_beat_spy": float(p_beat_spy),
            "n_windows": len(metrics_list),
        }

        print(f"  {name:25s} | {np.mean(sharpes):8.3f} {np.median(sharpes):8.3f} {np.min(sharpes):8.3f} | "
              f"{np.mean(cagrs):10.4f} {np.median(cagrs):10.4f} {np.min(cagrs):11.4f} | "
              f"{np.mean(mdds):9.4f} {np.min(mdds):10.4f} | "
              f"{p_positive:6.1%} {p_beat_spy:8.1%}")

    all_results[f"{h}yr"] = horizon_data

    # ── Determine best strategy for this horizon ──
    # Criterion: highest mean Sharpe (risk-adjusted), with worst-case CAGR as tiebreaker
    best_name = None
    best_mean_sharpe = -999
    for name, d in horizon_data.items():
        if d["mean_sharpe"] > best_mean_sharpe:
            best_mean_sharpe = d["mean_sharpe"]
            best_name = name

    # Also find safest (highest P(positive)) and best minimax (least bad worst-case CAGR)
    safest_name = max(horizon_data.items(), key=lambda x: x[1]["p_positive"])[0]
    minimax_name = max(horizon_data.items(), key=lambda x: x[1]["worst_cagr"])[0]

    horizon_recommendations[f"{h}yr"] = {
        "best_risk_adjusted": best_name,
        "best_mean_sharpe": best_mean_sharpe,
        "safest_strategy": safest_name,
        "safest_p_positive": horizon_data[safest_name]["p_positive"],
        "minimax_strategy": minimax_name,
        "minimax_worst_cagr": horizon_data[minimax_name]["worst_cagr"],
    }

# ─────────────────────────────────────────────────────────
# 4. CROSSOVER ANALYSIS
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Crossover Analysis: Where does the best strategy change?")
print("=" * 70)

print(f"\n  {'Horizon':>8s} | {'Best (Sharpe)':25s} | {'Safest (P>0)':25s} | {'Minimax (worst CAGR)':25s}")
print("  " + "-" * 95)

for h_key, rec in horizon_recommendations.items():
    print(f"  {h_key:>8s} | {rec['best_risk_adjusted']:25s} | "
          f"{rec['safest_strategy']:25s} | {rec['minimax_strategy']:25s}")

# ─────────────────────────────────────────────────────────
# 5. PRACTICAL RECOMMENDATION TABLE
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Practical Recommendations by Investor Horizon")
print("=" * 70)

# Group horizons into practical buckets
buckets = {
    "1-3 years (conservative/retiree)": ["1yr", "2yr", "3yr"],
    "3-5 years (medium-term)": ["3yr", "5yr"],
    "5-10 years (growth)": ["5yr", "7yr", "10yr"],
    "10+ years (long-term accumulation)": ["10yr", "15yr", "20yr"],
}

practical_recs = {}

for bucket_name, horizons in buckets.items():
    available = [h for h in horizons if h in horizon_recommendations]
    if not available:
        continue

    # Aggregate: count how often each strategy wins across horizons in this bucket
    sharpe_votes = {}
    safety_votes = {}
    minimax_votes = {}

    for h in available:
        rec = horizon_recommendations[h]
        sharpe_votes[rec["best_risk_adjusted"]] = sharpe_votes.get(rec["best_risk_adjusted"], 0) + 1
        safety_votes[rec["safest_strategy"]] = safety_votes.get(rec["safest_strategy"], 0) + 1
        minimax_votes[rec["minimax_strategy"]] = minimax_votes.get(rec["minimax_strategy"], 0) + 1

    best_sharpe = max(sharpe_votes, key=sharpe_votes.get)
    best_safety = max(safety_votes, key=safety_votes.get)
    best_minimax = max(minimax_votes, key=minimax_votes.get)

    # Get average metrics for the winning strategy across horizons
    avg_metrics = {}
    for h in available:
        if h in all_results and best_sharpe in all_results[h]:
            for k, v in all_results[h][best_sharpe].items():
                if k not in avg_metrics:
                    avg_metrics[k] = []
                avg_metrics[k].append(v)

    avg_sharpe = np.mean(avg_metrics.get("mean_sharpe", [0]))
    avg_cagr = np.mean(avg_metrics.get("mean_cagr", [0]))
    avg_p_pos = np.mean(avg_metrics.get("p_positive", [0]))

    practical_recs[bucket_name] = {
        "recommended_strategy": best_sharpe,
        "safety_pick": best_safety,
        "minimax_pick": best_minimax,
        "avg_mean_sharpe": float(avg_sharpe),
        "avg_mean_cagr": float(avg_cagr),
        "avg_p_positive": float(avg_p_pos),
    }

    print(f"\n  {bucket_name}")
    print(f"    Best risk-adjusted: {best_sharpe}")
    print(f"    Safest (P>0):       {best_safety}")
    print(f"    Minimax (worst):    {best_minimax}")
    print(f"    Avg mean Sharpe:    {avg_sharpe:.3f}")
    print(f"    Avg mean CAGR:     {avg_cagr:.4f}")
    print(f"    Avg P(positive):    {avg_p_pos:.1%}")

# ─────────────────────────────────────────────────────────
# 6. STRATEGY DOMINANCE HEATMAP DATA
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Strategy Ranking by Horizon (Mean Sharpe)")
print("=" * 70)

strat_names = list(strategies.keys())
print(f"\n  {'Horizon':>8s}", end="")
for name in strat_names:
    print(f" | {name:>15s}", end="")
print(" | Rank Order")
print("  " + "-" * 120)

ranking_table = {}
for h_key in [f"{h}yr" for h in HORIZONS_YEARS]:
    if h_key not in all_results:
        continue
    horizon_data = all_results[h_key]
    sharpes = {}
    for name in strat_names:
        if name in horizon_data:
            sharpes[name] = horizon_data[name]["mean_sharpe"]
        else:
            sharpes[name] = -999

    ranked = sorted(sharpes.items(), key=lambda x: x[1], reverse=True)
    ranking_table[h_key] = [r[0] for r in ranked]

    print(f"  {h_key:>8s}", end="")
    for name in strat_names:
        s = sharpes[name]
        print(f" | {s:15.3f}", end="")
    rank_str = " > ".join([f"{r[0][:8]}" for r in ranked[:3]])
    print(f" | {rank_str}")

# ─────────────────────────────────────────────────────────
# 7. KEY FINDING: THE CROSSOVER POINT
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("KEY FINDING: Crossover Analysis")
print("=" * 70)

# Track when each strategy is #1
for h_key, ranking in ranking_table.items():
    winner = ranking[0]
    rec = horizon_recommendations[h_key]
    print(f"  {h_key:>6s}: #1 = {winner:25s} (Sharpe={rec['best_mean_sharpe']:.3f})")

# ─────────────────────────────────────────────────────────
# 8. WORST-CASE ANALYSIS (IMPORTANT FOR RISK-AVERSE)
# ─────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("Worst-Case CAGR by Horizon (for risk-averse investors)")
print("=" * 70)

print(f"\n  {'Horizon':>8s}", end="")
for name in strat_names:
    print(f" | {name:>15s}", end="")
print()
print("  " + "-" * 100)

for h_key in [f"{h}yr" for h in HORIZONS_YEARS]:
    if h_key not in all_results:
        continue
    print(f"  {h_key:>8s}", end="")
    for name in strat_names:
        if name in all_results[h_key]:
            wc = all_results[h_key][name]["worst_cagr"]
            print(f" | {wc:14.3%}", end="")
        else:
            print(f" | {'N/A':>15s}", end="")
    print()

# ─────────────────────────────────────────────────────────
# 9. SAVE RESULTS
# ─────────────────────────────────────────────────────────
results = {
    "experiment_id": "K655",
    "title": "Optimal Strategy by Investment Horizon",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "data_period": f"{START} to {END}",
    "sample_size": int(len(dates)),
    "horizons_years": HORIZONS_YEARS,
    "step_days": STEP_DAYS,
    "strategies": list(strategies.keys()),
    "risk_free_rate": 0.02,
    "methodology": (
        "Rolling window analysis: for each horizon h, compute ALL possible "
        "h-year periods (step=21 trading days). In each window compute "
        "Sharpe (excess over 2% RF), CAGR, MDD. Report mean/median/worst/best "
        "and probability of positive return / beating SPY BH."
    ),
    "horizon_results": all_results,
    "horizon_recommendations": horizon_recommendations,
    "practical_recommendations": practical_recs,
    "ranking_table": ranking_table,
    "references": [
        "K569: Piecewise VT validation",
        "K574: Piecewise calibration",
        "K640: Live performance audit",
        "K645: GLD role (80/20 optimal with 12/VIX)",
        "K646: Cross-OOS 80/20 vs 50/50",
        "K654: Piecewise decomposition",
    ],
}

output_path = "experiments/k655_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {output_path}")
print("\nDone.")
