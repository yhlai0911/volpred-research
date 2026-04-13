"""K1121 plots: Sharpe bar, MDD bar, equity curves, OOS rolling Sharpe, stress periods."""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT_DIR = Path(__file__).parent
DATA_DIR = OUT_DIR / "data"

with open(OUT_DIR / "k1121_results.json") as f:
    R = json.load(f)

strategies = ["S1", "S2", "S3", "S4", "S5", "S6"]
labels = {
    "S1": "S1\n50/50",
    "S2": "S2\nVol-target",
    "S3": "S3\nVIX-regime",
    "S4": "S4\nEPU-regime",
    "S5": "S5\nNFCI-regime",
    "S6": "S6\nHybrid",
}
colors = {"S1": "#555", "S2": "#888", "S3": "#2e7", "S4": "#d44", "S5": "#47d", "S6": "#c4c"}

fm = R["full_sample_metrics"]

# -------- Fig 1: Sharpe comparison (full / IS / OOS) --------
fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
for ax, label in zip(axes, ["full", "IS", "OOS"]):
    vals = []
    for s in strategies:
        if label == "full":
            vals.append(fm[s]["sharpe"])
        else:
            vals.append(R["is_oos_metrics"][label][s]["sharpe"])
    bars = ax.bar(range(len(strategies)), vals, color=[colors[s] for s in strategies])
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels([labels[s] for s in strategies], fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.axhline(vals[0], color=colors["S1"], lw=0.8, ls="--", alpha=0.6, label="S1 baseline")
    ax.set_ylabel("Sharpe ratio")
    ax.set_title(f"{label.upper()} Sharpe")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                ha="center", va="bottom", fontsize=8)
    ax.grid(axis="y", alpha=0.3)
plt.suptitle("K1121: 6-Strategy Sharpe Comparison (SPY+GLD portfolio, 2019-2026)", fontsize=11)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1121_sharpe_comparison.png", dpi=130, bbox_inches="tight")
plt.close()

# -------- Fig 2: MDD and Calmar --------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
mdds = [fm[s]["max_drawdown"] for s in strategies]
calmars = [fm[s]["calmar"] for s in strategies]
bars1 = ax1.bar(range(len(strategies)), mdds, color=[colors[s] for s in strategies])
ax1.set_xticks(range(len(strategies)))
ax1.set_xticklabels([labels[s] for s in strategies], fontsize=9)
ax1.set_ylabel("Max Drawdown")
ax1.set_title("Max Drawdown")
ax1.axhline(-0.2, color="red", lw=0.5, ls=":", alpha=0.5, label="-20% threshold")
ax1.legend(fontsize=8)
ax1.grid(axis="y", alpha=0.3)
for b, v in zip(bars1, mdds):
    ax1.text(b.get_x() + b.get_width()/2, v - 0.01, f"{v:.1%}",
             ha="center", va="top", fontsize=8)

bars2 = ax2.bar(range(len(strategies)), calmars, color=[colors[s] for s in strategies])
ax2.set_xticks(range(len(strategies)))
ax2.set_xticklabels([labels[s] for s in strategies], fontsize=9)
ax2.set_ylabel("Calmar (ann_ret / |MDD|)")
ax2.set_title("Calmar ratio")
ax2.grid(axis="y", alpha=0.3)
for b, v in zip(bars2, calmars):
    ax2.text(b.get_x() + b.get_width()/2, v + 0.015, f"{v:.2f}",
             ha="center", va="bottom", fontsize=8)
plt.suptitle("K1121: Risk metrics", fontsize=11)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1121_risk_metrics.png", dpi=130, bbox_inches="tight")
plt.close()

# -------- Fig 3: Equity curves --------
bt = pd.read_parquet(DATA_DIR / "backtest.parquet")
fig, ax = plt.subplots(figsize=(11, 5))
for s in strategies:
    eq = (1 + bt[f"r_{s}"]).cumprod()
    ax.plot(eq.index, eq.values, label=f"{s} SR={fm[s]['sharpe']:.2f}",
            color=colors[s], lw=1.2, alpha=0.85)
ax.set_title("K1121: Cumulative returns 2019-2026 (SPY+GLD portfolio, $1 start)")
ax.set_ylabel("Wealth (×)")
ax.legend(fontsize=9, ncol=2)
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1121_equity_curves.png", dpi=130, bbox_inches="tight")
plt.close()

# -------- Fig 4: Bootstrap differences vs S1 --------
fig, ax = plt.subplots(figsize=(9, 4.5))
boot = R["bootstrap_vs_S1_50_50"]
strat_names = ["S2", "S3", "S4", "S5", "S6"]
diffs = [boot[f"{s}_vs_S1"]["obs_diff"] for s in strat_names]
p_vals = [boot[f"{s}_vs_S1"]["p_value"] for s in strat_names]
ci_lows = [boot[f"{s}_vs_S1"]["ci_low"] for s in strat_names]
ci_highs = [boot[f"{s}_vs_S1"]["ci_high"] for s in strat_names]
x = np.arange(len(strat_names))
errs_low = [d - lo for d, lo in zip(diffs, ci_lows)]
errs_high = [hi - d for d, hi in zip(diffs, ci_highs)]
bars = ax.bar(x, diffs, yerr=[errs_low, errs_high], capsize=5,
              color=[colors[s] for s in strat_names],
              edgecolor="black", lw=0.5)
ax.set_xticks(x)
ax.set_xticklabels([labels[s] for s in strat_names], fontsize=9)
ax.axhline(0, color="black", lw=0.8)
ax.set_ylabel("Sharpe difference vs S1 (50/50)")
ax.set_title("K1121: Bootstrap Sharpe difference vs 50/50 baseline (95% CI, 1000 reps)")
for i, (d, p) in enumerate(zip(diffs, p_vals)):
    ax.text(i, d + (0.03 if d >= 0 else -0.03), f"p={p:.2f}",
            ha="center", va="bottom" if d >= 0 else "top", fontsize=8)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1121_bootstrap_vs_5050.png", dpi=130, bbox_inches="tight")
plt.close()

# -------- Fig 5: Stress episode weights --------
stress = R["stress_episodes"]
fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=True)
for ax, (name, info) in zip(axes, stress.items()):
    d = info["by_strategy"]
    weights = [d[s]["avg_wSPY"] for s in strategies]
    bars = ax.bar(range(len(strategies)), weights, color=[colors[s] for s in strategies])
    ax.set_xticks(range(len(strategies)))
    ax.set_xticklabels([labels[s] for s in strategies], fontsize=9)
    ax.axhline(0.5, color="black", lw=0.5, ls="--", alpha=0.6)
    ax.set_ylabel("Avg wSPY" if ax == axes[0] else "")
    ax.set_title(f"{name}\n({info['period'][0]} to {info['period'][1]})", fontsize=10)
    ax.set_ylim(0, 1.0)
    ax.grid(axis="y", alpha=0.3)
    for b, v in zip(bars, weights):
        ax.text(b.get_x() + b.get_width()/2, v + 0.02, f"{v:.2f}",
                ha="center", va="bottom", fontsize=7)
plt.suptitle("K1121: Average SPY weight during stress episodes\n(Did alt-data reduce equity weight in stress?)", fontsize=11)
plt.tight_layout()
plt.savefig(OUT_DIR / "k1121_stress_weights.png", dpi=130, bbox_inches="tight")
plt.close()

print("Plots saved:")
for p in OUT_DIR.glob("*.png"):
    print(f"  {p.name}")
