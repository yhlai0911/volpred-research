"""
K1378 — DM t-stat across 3 sub-periods bar chart.
Harvey ±3.0 threshold lines included.
Output: experiments/k1378/k1378_dm_subperiods.png
"""
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

HERE = Path(__file__).parent
results_path = HERE / "k1378_results.json"
out_path = HERE / "k1378_dm_subperiods.png"

with open(results_path) as f:
    res = json.load(f)

# ---- Data ----------------------------------------------------------------
labels = ["全期 OOS\n(n=1,852)", "排除 COVID\n(n=1,515)", "僅 COVID\n(n=337)"]
dm_vals = [
    res["full_oos"]["dm_t_stat"],
    res["no_covid_oos"]["dm_t_stat"],
    res["covid_only_oos"]["dm_t_stat"],
]
# DM t < 0 means A4f better than GJR (lower QLIKE)
colors = ["#4C72B0", "#DD8452", "#55A868"]

# ---- Plot ----------------------------------------------------------------
fig, ax = plt.subplots(figsize=(8, 5))

bars = ax.bar(labels, dm_vals, color=colors, width=0.5, zorder=3,
              edgecolor="white", linewidth=0.8)

# Harvey threshold lines
for y, ls, label in [
    (3.0,  "--", "Harvey 門檻 +3.0"),
    (-3.0, "--", "Harvey 門檻 -3.0"),
]:
    ax.axhline(y, linestyle=ls, color="#CC0000", linewidth=1.4,
               zorder=4, label=label)

# Zero line
ax.axhline(0, color="#999999", linewidth=0.8, zorder=2)

# Value labels on bars
for bar, v in zip(bars, dm_vals):
    va_off = 0.07 if v >= 0 else -0.12
    ax.text(bar.get_x() + bar.get_width() / 2,
            v + va_off, f"{v:.2f}",
            ha="center", va="bottom" if v >= 0 else "top",
            fontsize=11, fontweight="bold", color="#222222")

# Shade "need to reach" zone (|t| > 3 for A4f to win)
ax.axhspan(-3.0, -5.0, alpha=0.06, color="#CC0000",
           label="A4f 須超越區（DM t < -3）")

ax.set_ylim(-3.5, 1.5)
ax.set_ylabel("DM t 統計量（A4f vs GJR-GARCH）", fontsize=11)
ax.set_title("K1378：三段期間 DM 統計量比較\nA4f 拿掉 COVID 後優勢消失", fontsize=12)
ax.tick_params(axis="x", labelsize=10)
ax.tick_params(axis="y", labelsize=10)
ax.grid(axis="y", alpha=0.3, zorder=0)

# Legend
handles, leg_labels = ax.get_legend_handles_labels()
# add custom bar patch for note
note_patch = mpatches.Patch(color="none", label="DM t < 0 = A4f 較佳")
ax.legend(handles=handles + [note_patch],
          labels=leg_labels + ["DM t < 0 = A4f 較佳"],
          fontsize=9, loc="upper right", framealpha=0.8)

fig.tight_layout()
fig.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"Saved: {out_path}")
