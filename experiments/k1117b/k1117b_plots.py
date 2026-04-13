"""Plots for K1117b monthly alt-data re-test."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

HERE = Path(__file__).parent

with open(HERE / "k1117b_results.json") as f:
    R = json.load(f)

loss_df = pd.read_csv(HERE / "k1117b_oos_loss_series.csv", parse_dates=[0], index_col=0)
pred_df = pd.read_csv(HERE / "k1117b_oos_predictions.csv", parse_dates=[0], index_col=0)


# -------------------------------------------------------------------
# Plot 1: DM t-stat bar chart with Harvey threshold
# -------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 5))
specs = []
tvals = []
colors = []
for name, d in R["dm_table_vs_vix"].items():
    specs.append(name.replace("M", "M").replace("_", " "))
    t = d["t_hln"]
    tvals.append(t)
    if d.get("harvey_pass") and t > 0:
        colors.append("#2ca02c")
    elif abs(t) > 3:
        colors.append("#d62728")
    else:
        colors.append("#7f7f7f")

bars = ax.barh(specs, tvals, color=colors, edgecolor="black")
ax.axvline(3, color="#2ca02c", linestyle="--", linewidth=1.5, label="Harvey +3 (challenger beats VIX)")
ax.axvline(-3, color="#d62728", linestyle="--", linewidth=1.5, label="Harvey -3 (VIX beats challenger)")
ax.axvline(0, color="black", linewidth=0.7)
ax.set_xlabel("DM-HLN t-statistic vs M2_vix baseline")
ax.set_title("K1117b: Monthly alt-data DM t-stats vs VIX baseline (SPY, OOS n=87 months)")
for b, t in zip(bars, tvals):
    ax.text(t + (0.05 if t >= 0 else -0.05), b.get_y() + b.get_height() / 2,
            f"{t:+.2f}", va="center", ha="left" if t >= 0 else "right", fontsize=9)
ax.set_xlim(-4, 4)
ax.legend(loc="lower right", fontsize=9)
ax.grid(axis="x", linestyle=":", alpha=0.4)
verdict = R["verdict"]
ax.text(0.02, 0.02, f"Verdict: {verdict}\nAll |t| < 3 → NULL robust at monthly frequency",
        transform=ax.transAxes, fontsize=10, verticalalignment="bottom",
        bbox=dict(boxstyle="round", facecolor="#ffffe0", alpha=0.9))
plt.tight_layout()
plt.savefig(HERE / "k1117b_dm_barchart.png", dpi=130, bbox_inches="tight")
plt.close()


# -------------------------------------------------------------------
# Plot 2: OOS cumulative QLIKE loss paths (vs VIX baseline)
# -------------------------------------------------------------------
fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)

# Actual RV vs M2_vix prediction
ax = axes[0]
pred_df["actual"].plot(ax=ax, label="Actual monthly RV", color="black", linewidth=1.5)
pred_df["M2_vix"].plot(ax=ax, label="M2_vix pred", color="#1f77b4", linewidth=1.3)
pred_df["M6_all"].plot(ax=ax, label="M6_all pred (VIX + 5 alt-data)", color="#d62728", linestyle="--", linewidth=1.1)
pred_df["M7_altonly"].plot(ax=ax, label="M7_altonly pred", color="#9467bd", linestyle=":", linewidth=1.1)
ax.set_ylabel("SPY Monthly RV (sqrt-scale)")
ax.set_title("K1117b: SPY monthly RV — Actual vs model predictions (OOS 2019-2026)")
ax.legend(loc="upper right", fontsize=9)
ax.grid(alpha=0.3)

# Cumulative loss differential (each spec - M2_vix)
ax = axes[1]
for name in loss_df.columns:
    if name == "M2_vix":
        continue
    diff = (loss_df[name] - loss_df["M2_vix"]).cumsum()
    ax.plot(diff.index, diff.values, label=f"{name} - M2_vix", linewidth=1.2)
ax.axhline(0, color="black", linewidth=0.6)
ax.set_ylabel("Cumulative QLIKE loss differential\n(positive = M2_vix wins)")
ax.set_xlabel("Month (OOS)")
ax.set_title("Cumulative OOS QLIKE loss differential vs VIX baseline")
ax.legend(loc="upper left", fontsize=9, ncol=2)
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(HERE / "k1117b_oos_paths.png", dpi=130, bbox_inches="tight")
plt.close()

print(f"Plots saved to {HERE}/k1117b_dm_barchart.png and k1117b_oos_paths.png")
