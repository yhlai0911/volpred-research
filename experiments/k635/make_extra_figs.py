#!/usr/bin/env python3
"""Generate two extra figures for K635 article:
  1. k635_qlike_comparison.png  — QLIKE rolling/fixed/ewma bar chart
  2. k635_sharpe_comparison.png — net Sharpe rolling/fixed/ewma/12vix/buy_hold

Numbers read directly from k635_results.json — no hard-coding.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent
results = json.loads((BASE / "k635_results.json").read_text())

# ----- Figure 1: QLIKE comparison -----
qlike = results["qlike_comparison"]
strategies = ["rolling", "fixed", "ewma"]
labels = ["Rolling refit\n(every 21d)", "Fixed params\n(pre-OOS, fixed)", "EWMA\n(λ=0.94)"]
values = [qlike[s] for s in strategies]
colors = ["#d62728", "#2ca02c", "#7f7f7f"]

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(labels, values, color=colors, edgecolor="black", width=0.55)
for b, v in zip(bars, values):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.003, f"{v:.4f}",
            ha="center", va="bottom", fontsize=11, fontweight="bold")

# highlight winner
win_idx = int(np.argmin(values))
bars[win_idx].set_color("#1f9e3d")
bars[win_idx].set_edgecolor("black")
bars[win_idx].set_linewidth(2.0)

ax.set_ylabel("QLIKE (lower = better)", fontsize=11)
ax.set_title("K635: QLIKE Forecast Loss — Fixed vs Rolling GARCH Parameters (SPY OOS 2023-2024)",
             fontsize=11, fontweight="bold")
y_min = min(values) - 0.015
y_max = max(values) + 0.015
ax.set_ylim(y_min, y_max)
ax.grid(axis="y", alpha=0.3)
# DM annotation
dm = results["dm_tests"]["qlike_rolling_vs_fixed"]
ax.text(0.98, 0.02,
        f"DM (rolling vs fixed): stat={dm['dm_statistic']:.2f}, p={dm['p_value']:.2e}\n"
        "rolling QLIKE 顯著高於 fixed",
        transform=ax.transAxes, fontsize=9, ha="right", va="bottom",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="#fff7e6", edgecolor="#ccc"))
plt.tight_layout()
out1 = BASE / "k635_qlike_comparison.png"
plt.savefig(out1, dpi=130, bbox_inches="tight")
plt.close()
print(f"WROTE {out1}")

# ----- Figure 2: Net Sharpe comparison -----
sp = results["spy_strategies"]
strat_keys = ["rolling_vt", "fixed_vt", "ewma_vt", "12vix", "buy_hold"]
strat_labels = ["Rolling VT", "Fixed VT", "EWMA VT", "12/VIX VT", "Buy & Hold SPY"]
# buy_hold has sharpe_ratio (no net version since no rebalancing in cost model);
# we use net_sharpe_ratio when present, else sharpe_ratio
sharpes = []
for k in strat_keys:
    rec = sp[k]
    sharpes.append(rec.get("net_sharpe_ratio", rec.get("sharpe_ratio")))

colors2 = ["#d62728", "#2ca02c", "#7f7f7f", "#1f77b4", "#9467bd"]
fig, ax = plt.subplots(figsize=(9, 5.2))
bars = ax.bar(strat_labels, sharpes, color=colors2, edgecolor="black", width=0.6)
for b, v in zip(bars, sharpes):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.04, f"{v:.3f}",
            ha="center", va="bottom", fontsize=10, fontweight="bold")

# annotate fixed beats rolling
rolling_s = sp["rolling_vt"]["net_sharpe_ratio"]
fixed_s = sp["fixed_vt"]["net_sharpe_ratio"]
delta = fixed_s - rolling_s
ax.annotate(f"Fixed − Rolling\nΔSharpe = +{delta:.3f}",
            xy=(1, fixed_s), xytext=(1.5, fixed_s + 0.45),
            fontsize=10, ha="center",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="#e8f5e9", edgecolor="#2ca02c"),
            arrowprops=dict(arrowstyle="->", color="#2ca02c", lw=1.4))

ax.set_ylabel("Net Sharpe (after 2bp tx cost)", fontsize=11)
ax.set_title("K635: Strategy Net Sharpe — SPY OOS 2023-2024 (target vol 10%)",
             fontsize=11, fontweight="bold")
ax.set_ylim(0, max(sharpes) * 1.18)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
out2 = BASE / "k635_sharpe_comparison.png"
plt.savefig(out2, dpi=130, bbox_inches="tight")
plt.close()
print(f"WROTE {out2}")
