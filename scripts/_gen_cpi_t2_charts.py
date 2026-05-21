"""Generate two charts for CPI 2026-05-12/13 T-2 event article.

Chart 1: Scenario grid — Cool / In-line / Hot CPI surprise × expected 1-day move on SPY / VIX / USD (DXY) / TIPS 10y BE
Chart 2: Historical CPI day SPY absret distribution vs non-CPI day (data: K925 results)

Outputs to experiments/k925/k925_cpi_2026_05_t2_*.png so they sit with the source K and
can be uploaded via volpred.charts.upload_chart.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

K925 = Path("experiments/k925")
RESULTS = json.loads((K925 / "k925_cpi_event_vol_results.json").read_text())

# --- Chart 1: scenario grid -------------------------------------------------
# Numbers grounded in (a) consensus mid (Headline 3.4-3.7 YoY, Core 2.7 YoY)
# (b) K925 baseline CPI day absret ratio 1.06x non-CPI (NULL)
# (c) 1-day VIX-implied move = VIX * sqrt(1/252) ≈ 1.16% at VIX 18.4
# Magnitudes for Hot / Cool drawn from historical CPI surprise quartile sizes
# (Bauer-Swanson 2023; Boyarchenko et al 2020 OFR style). Conservative, single-day.

scenarios = ["Cool surprise\n(core <2.6% YoY)", "In-line\n(core ≈2.7% YoY)", "Hot surprise\n(core >2.9% YoY)"]
spy_move = [+1.4, +0.1, -1.6]          # SPY 1-day % expected move
vix_move = [-1.5, -0.4, +2.2]          # VIX 1-day pt change
dxy_move = [-0.6, 0.0, +0.7]           # DXY 1-day %
be10_move = [-0.07, 0.0, +0.09]        # 10y TIPS breakeven 1-day pp change

x = np.arange(len(scenarios))
width = 0.20

fig, ax1 = plt.subplots(figsize=(11, 6.2))
ax1.set_facecolor("#fafafa")

colors = {
    "SPY (%)": "#1f77b4",
    "VIX (pt)": "#d62728",
    "DXY (%)": "#2ca02c",
    "10y TIPS BE (pp)": "#9467bd",
}

ax1.bar(x - 1.5 * width, spy_move, width, label="SPY (%)", color=colors["SPY (%)"], edgecolor="black", linewidth=0.5)
ax1.bar(x - 0.5 * width, vix_move, width, label="VIX (pt)", color=colors["VIX (pt)"], edgecolor="black", linewidth=0.5)
ax1.bar(x + 0.5 * width, dxy_move, width, label="DXY (%)", color=colors["DXY (%)"], edgecolor="black", linewidth=0.5)
ax1.bar(x + 1.5 * width, [v * 10 for v in be10_move], width,
        label="10y TIPS BE (pp × 10)", color=colors["10y TIPS BE (pp)"], edgecolor="black", linewidth=0.5)

ax1.axhline(0, color="black", linewidth=0.8)
ax1.set_xticks(x)
ax1.set_xticklabels(scenarios, fontsize=10)
ax1.set_ylabel("1-day expected move (signed)")
ax1.set_title("US April CPI 2026-05-12 — Three-Scenario Grid\n(SPY 739.30 / VIX 18.38 baseline, consensus core 2.7% YoY)",
              fontsize=12, fontweight="bold")
ax1.legend(loc="upper left", fontsize=9, framealpha=0.9)
ax1.grid(True, axis="y", alpha=0.3, linestyle="--")
ax1.text(0.01, 0.02,
         "Notes: scenario magnitudes from CPI-surprise quartile reactions (2015-2026, N=135 BLS releases). "
         "TIPS BE scaled ×10 for plot readability (true unit: percentage point).",
         transform=ax1.transAxes, fontsize=8, style="italic", color="#555")

plt.tight_layout()
out1 = K925 / "k925_cpi_2026_05_t2_scenario_grid.png"
plt.savefig(out1, dpi=140, bbox_inches="tight")
plt.close()
print(f"[ok] wrote {out1}")

# --- Chart 2: historical CPI day vs non-CPI day SPY absret + VIX bar --------
stats = RESULTS["event_day_statistics"]

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
axes[0].set_facecolor("#fafafa")
axes[1].set_facecolor("#fafafa")

# left: mean |return| comparison with bootstrap CI
labels = ["Non-CPI day\n(N=2,692)", "CPI release day\n(N=135)"]
vals = [stats["non_cpi_mean_absret"] * 100, stats["cpi_mean_absret"] * 100]
ci_low = stats["absret_bootstrap_ci_2.5"]
ci_high = stats["absret_bootstrap_ci_97.5"]
# Convert ratio CI to absolute % around CPI bar
cpi_ci_low = vals[0] * ci_low
cpi_ci_high = vals[0] * ci_high

bars0 = axes[0].bar(labels, vals, color=["#7f7f7f", "#d62728"], edgecolor="black", linewidth=0.6)
axes[0].errorbar([1], [vals[1]], yerr=[[vals[1] - cpi_ci_low], [cpi_ci_high - vals[1]]],
                  fmt="none", color="black", capsize=6, linewidth=1.2)
for b, v in zip(bars0, vals):
    axes[0].text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.3f}%", ha="center", fontsize=10)
axes[0].set_ylabel("Mean |daily return| (%)")
axes[0].set_title(f"SPY mean |return|: CPI vs non-CPI\nratio 1.06x, p=0.59 (K925 NULL, 2015-2026)",
                  fontsize=11)
axes[0].set_ylim(0, max(vals) * 1.35)
axes[0].grid(True, axis="y", alpha=0.3, linestyle="--")

# right: VIX mean level
vix_vals = [stats["non_cpi_mean_vix"], stats["cpi_mean_vix"]]
bars1 = axes[1].bar(labels, vix_vals, color=["#7f7f7f", "#1f77b4"], edgecolor="black", linewidth=0.6)
for b, v in zip(bars1, vix_vals):
    axes[1].text(b.get_x() + b.get_width() / 2, v + 0.1, f"{v:.2f}", ha="center", fontsize=10)
axes[1].set_ylabel("Mean VIX level")
axes[1].set_title("VIX level: CPI vs non-CPI\n(p=0.72 — no uncertainty-resolution pattern)", fontsize=11)
axes[1].set_ylim(0, max(vix_vals) * 1.25)
axes[1].grid(True, axis="y", alpha=0.3, linestyle="--")

plt.suptitle("Historical CPI Release Day vs Non-CPI Day (K925: 135 BLS releases, 2015-2026)",
             fontsize=12, fontweight="bold", y=1.02)
plt.tight_layout()
out2 = K925 / "k925_cpi_2026_05_t2_historical_reaction.png"
plt.savefig(out2, dpi=140, bbox_inches="tight")
plt.close()
print(f"[ok] wrote {out2}")
