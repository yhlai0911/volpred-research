#!/usr/bin/env python3
"""Scatter: overnight variance share (x) vs strength-of-edge (y) across 6 markets.
Numbers read programmatically from experiments/k1710/K1710_results.json.
Palette follows the dataviz skill reference instance (light surface)."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
data = json.load(open(ROOT / "experiments/k1710/K1710_results.json"))
mk = data["markets"]

rows = []
for name, v in mk.items():
    op = v["dm_tests"]["open_panel_main"]
    rows.append(
        {
            "name": name,
            "share": v["oos_overnight_variance_share"] * 100.0,
            "edge": abs(op["t_stat"]),
            "sig": abs(op["t_stat"]) >= 3.0,
        }
    )

# dataviz reference palette (light)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BLUE = "#2a78d6"      # categorical slot 1 — clear edge
ORANGE = "#eb6834"    # categorical slot 2 — edge but not decisive
TREND = "#c3c2b7"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [
            "PingFang TC",
            "Heiti TC",
            "Arial Unicode MS",
            "Noto Sans CJK TC",
            "sans-serif",
        ],
        "axes.unicode_minus": False,
    }
)

fig, ax = plt.subplots(figsize=(8.4, 5.6), dpi=150)
fig.patch.set_facecolor(SURFACE)
ax.set_facecolor(SURFACE)

# faint fitted trend line (visual guide for the positive relationship)
xs = [r["share"] for r in rows]
ys = [r["edge"] for r in rows]
n = len(xs)
mx = sum(xs) / n
my = sum(ys) / n
b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
a = my - b * mx
lo, hi = min(xs) - 3, max(xs) + 3
ax.plot([lo, hi], [a + b * lo, a + b * hi], color=TREND, lw=2, zorder=1)

for r in rows:
    color = BLUE if r["sig"] else ORANGE
    ax.scatter(
        r["share"], r["edge"], s=170, color=color, zorder=3,
        edgecolors=SURFACE, linewidths=2,
    )
    dy = 0.45 if r["name"] != "EEM" else -0.75
    ha = "center"
    ax.annotate(
        r["name"], (r["share"], r["edge"]), textcoords="offset points",
        xytext=(0, 11 if dy > 0 else -16), ha=ha, fontsize=11.5,
        color=INK, fontweight="bold",
    )

# legend via proxy handles
from matplotlib.lines import Line2D

handles = [
    Line2D([0], [0], marker="o", color="none", markerfacecolor=BLUE,
           markersize=11, label="優勢明確（把握度高）"),
    Line2D([0], [0], marker="o", color="none", markerfacecolor=ORANGE,
           markersize=11, label="有優勢但不夠決定性"),
]
leg = ax.legend(handles=handles, loc="upper left", frameon=False,
                fontsize=10.5, labelcolor=INK2)

ax.set_xlabel("隔夜佔全日風險的比重（%）", fontsize=12, color=INK2)
ax.set_ylabel("開盤資訊帶來的預測優勢強度", fontsize=12, color=INK2)
ax.set_title("風險越集中在隔夜，開盤資訊越有用", fontsize=15,
             color=INK, fontweight="bold", pad=14)

ax.grid(True, color=GRID, lw=1, zorder=0)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color("#c3c2b7")
ax.tick_params(colors=MUTED, labelsize=10)
ax.set_xlim(lo, hi)
ax.set_ylim(0, max(ys) + 1.6)

fig.tight_layout()
out = Path(__file__).resolve().parent / "k1710_overnight_edge.png"
fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
print("wrote", out)
