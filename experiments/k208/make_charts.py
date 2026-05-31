"""
K208 Chart Generator
Two charts from k208_implied_realized_gap_results.json:
  1. k208_oos_r2_comparison.png — OOS R² bar chart for 4 models
  2. k208_regime_returns.png — OOS 4-regime avg 22-day return bar chart with error bars
"""

import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

np.random.seed(42)

BASE_DIR = Path(__file__).parent
RESULTS_FILE = BASE_DIR / "k208_implied_realized_gap_results.json"

with open(RESULTS_FILE) as f:
    results = json.load(f)

pred = results["predictive_power"]
regime = results["regime_analysis"]["oos_regime_stats"]

# ── Chart 1: OOS R² comparison ───────────────────────────────────────────────
labels = ["VIX alone", "GARCH alone", "VIX + Gap", "Gap ratio alone"]
r2_vals = [
    pred["oos_r2_vix_alone"] * 100,
    pred["oos_r2_garch_alone"] * 100,
    pred["oos_r2_vix_plus_gap"] * 100,
    pred["oos_r2_gap_ratio_alone"] * 100,
]
colors = ["#2563EB", "#6B7280", "#FBBF24", "#DC2626"]

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(labels, r2_vals, color=colors, width=0.55, edgecolor="white", linewidth=1.2)

# Annotate bars
for bar, val in zip(bars, r2_vals):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + 0.15,
        f"{val:.2f}%",
        ha="center", va="bottom", fontsize=11, fontweight="bold"
    )

ax.set_ylabel("OOS R² (%)", fontsize=12)
ax.set_title(
    "OOS Forecast Performance: VIX vs GARCH vs Gap\n(SPY 2023–2024, 5-day ahead realized vol)",
    fontsize=12, pad=12
)
ax.set_ylim(0, max(r2_vals) * 1.25)
ax.spines[["top", "right"]].set_visible(False)
ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E5E7EB")
ax.set_axisbelow(True)

# Annotate the near-identical VIX and VIX+Gap bars
ax.annotate(
    f"F-stat: {pred['f_test_stat']:.3f}\np = {pred['f_test_pval']:.3f}",
    xy=(2, r2_vals[2]),
    xytext=(2.4, r2_vals[2] - 3),
    fontsize=9.5, color="#374151",
    arrowprops=dict(arrowstyle="->", color="#374151", lw=1),
)

plt.tight_layout()
out1 = BASE_DIR / "k208_oos_r2_comparison.png"
fig.savefig(out1, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out1}")

# ── Chart 2: OOS regime avg 22-day returns ────────────────────────────────────
regime_order = ["High Fear", "Moderate High", "Moderate Low", "Complacent"]
regime_labels = ["High Fear\n(gap 最大)", "Moderate High", "Moderate Low", "Complacent\n(gap 最小)"]
avg_rets = [regime[r]["avg_22d_ret"] * 100 for r in regime_order]
vol_rets = [regime[r]["vol_22d_ret"] * 100 for r in regime_order]
counts = [regime[r]["count"] for r in regime_order]
colors2 = ["#DC2626", "#F97316", "#FBBF24", "#22C55E"]

fig, ax = plt.subplots(figsize=(8, 5))
bars2 = ax.bar(
    regime_labels, avg_rets,
    color=colors2, width=0.55, edgecolor="white", linewidth=1.2,
    yerr=vol_rets, capsize=5, error_kw=dict(ecolor="#374151", elinewidth=1.5)
)

for bar, val, n in zip(bars2, avg_rets, counts):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height() + max(vol_rets) * 0.15,
        f"{val:.2f}%\n(n={n})",
        ha="center", va="bottom", fontsize=10
    )

ax.set_ylabel("平均 22 日報酬 (%)", fontsize=12)
ax.set_title(
    "OOS Regime Analysis: Gap Level → Future 22-Day Return\n(SPY 2023–2024; error bar = 1 std dev)",
    fontsize=12, pad=12
)
ax.set_ylim(0, max(avg_rets) * 2.8)
ax.spines[["top", "right"]].set_visible(False)
ax.yaxis.grid(True, linestyle="--", alpha=0.5, color="#E5E7EB")
ax.set_axisbelow(True)

# p-value annotation
ttest = results["regime_analysis"]["regime_ttest"]
ax.text(
    0.97, 0.95,
    f"Regime t-test p = {ttest['p']:.3f}",
    transform=ax.transAxes, ha="right", va="top", fontsize=10,
    color="#6B7280", style="italic"
)

plt.tight_layout()
out2 = BASE_DIR / "k208_regime_returns.png"
fig.savefig(out2, dpi=150, bbox_inches="tight")
plt.close(fig)
print(f"Saved: {out2}")
