#!/usr/bin/env python3
"""Regenerate Figure 2 (cross-asset scatter) from K1695 canonical data.

Source: experiments/k1695/figure2_data.csv (inception-aware rows, pinned snapshot).
Replaces the stale-vintage fig2_cross_asset_scatter.pdf (old averages -0.048/24.9).
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DATA = REPO / "experiments" / "k1695" / "figure2_data.csv"

df = pd.read_csv(DATA)
assert len(df) == 13, f"expected 13 markets, got {len(df)}"

avg_ds = df["delta_sharpe"].mean()
avg_dm = df["delta_mdd_pp"].mean()
# Guard: must match the paper's Table 5 averages (K1695 canonical)
assert abs(avg_ds - (-0.044)) < 0.001, avg_ds
assert abs(avg_dm - 27.5) < 0.05, avg_dm

plt.rcParams.update({"font.family": "serif", "font.size": 10})
fig, ax = plt.subplots(figsize=(7.0, 5.2))

for region, marker, color, label in [
    ("DM", "o", "#1f4e8c", "Developed ($N=7$)"),
    ("EM", "s", "#a33c3c", "Emerging ($N=6$)"),
]:
    sub = df[df["region"] == region]
    ax.scatter(sub["delta_sharpe"], sub["delta_mdd_pp"], marker=marker,
               s=55, c=color, label=label, zorder=3)
    for _, r in sub.iterrows():
        ax.annotate(r["ticker"], (r["delta_sharpe"], r["delta_mdd_pp"]),
                    textcoords="offset points", xytext=(6, 4), fontsize=8)

ax.axvline(avg_ds, ls=":", c="gray", lw=1)
ax.axhline(avg_dm, ls=":", c="gray", lw=1)
ax.axvline(0, ls="-", c="black", lw=0.6)
ax.axhline(0, ls="-", c="black", lw=0.6)
ax.set_xlabel(r"$\Delta$Sharpe (VT $-$ BH)")
ax.set_ylabel(r"$\Delta$MDD improvement (pp)")
ax.legend(loc="lower left", frameon=False)
ax.set_axisbelow(True)
ax.grid(alpha=0.25, lw=0.5)
fig.tight_layout()
fig.savefig(HERE / "fig2_cross_asset_scatter.pdf")
fig.savefig(HERE / "fig2_cross_asset_scatter.png", dpi=300)
print(f"OK avg_dSharpe={avg_ds:.4f} avg_dMDD={avg_dm:.2f}pp -> fig2_cross_asset_scatter.pdf/png")
