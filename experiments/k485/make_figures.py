"""K485 figures for general-audience article.

Generates 3 figures from k485_ssvs_vareq_cross_oos_results.json:
  fig1_qlike_by_period.png — 5-period QLIKE comparison line chart
  fig2_dm_pvalue_by_period.png — DM p-value bar chart (SSVS vs GJR)
  fig3_avg_qlike_ranking.png — average QLIKE across 5 periods, all 5 models
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).parent
DATA = ROOT / "k485_ssvs_vareq_cross_oos_results.json"
OUT = ROOT

with DATA.open() as fh:
    R = json.load(fh)

periods = list(R["cross_oos_results"].keys())
period_short = ["2015-16", "2017-18\n(Volmageddon)", "2019-20\n(COVID)", "2021-22\n(rate hikes)", "2023-24"]

models = ["Base GARCH(1,1)", "GJR-GARCH(1,1)", "SSVS Median (GJR+VIX+Range+|ε|)", "GJR + VIX only", "GJR + Range only"]
colors = {"Base GARCH(1,1)": "#9aa0a6", "GJR-GARCH(1,1)": "#1f77b4", "SSVS Median (GJR+VIX+Range+|ε|)": "#d62728", "GJR + VIX only": "#2ca02c", "GJR + Range only": "#ff7f0e"}
labels = {"Base GARCH(1,1)": "Base GARCH", "GJR-GARCH(1,1)": "GJR-GARCH", "SSVS Median (GJR+VIX+Range+|ε|)": "SSVS (4 vars)", "GJR + VIX only": "GJR+VIX (best avg)", "GJR + Range only": "GJR+Range"}

# ---------------- Fig 1: QLIKE per period ----------------
fig, ax = plt.subplots(figsize=(9.5, 5.2))
x = np.arange(len(periods))
for m in models:
    qs = [R["cross_oos_results"][p]["model_metrics"][m]["QLIKE"] for p in periods]
    lw = 2.6 if "SSVS" in m or "VIX only" in m else 1.6
    ls = "-" if "SSVS" in m or "VIX only" in m else "--"
    ax.plot(x, qs, marker="o", color=colors[m], label=labels[m], linewidth=lw, linestyle=ls, markersize=7)
ax.set_xticks(x)
ax.set_xticklabels(period_short, fontsize=9)
ax.set_ylabel("QLIKE  (lower is better)", fontsize=11)
ax.set_title("K485 SSVS Cross-OOS Validation: 5 OOS Periods on SPY", fontsize=12)
ax.grid(alpha=0.3)
ax.legend(fontsize=9, loc="upper right", framealpha=0.9)
plt.tight_layout()
plt.savefig(OUT / "fig1_qlike_by_period.png", dpi=140, bbox_inches="tight")
plt.close()

# ---------------- Fig 2: DM p-value SSVS vs GJR ----------------
fig, ax = plt.subplots(figsize=(9.0, 4.8))
pvals = [s["dm_pval"] for s in R["ssvs_vs_gjr_summary"]]
better = [s["ssvs_better"] for s in R["ssvs_vs_gjr_summary"]]
bar_colors = ["#d62728" if b and p < 0.10 else ("#1f77b4" if b else "#9aa0a6") for b, p in zip(better, pvals)]
bars = ax.bar(period_short, pvals, color=bar_colors, edgecolor="black", linewidth=0.6)
ax.axhline(0.05, color="black", linestyle="--", linewidth=1, label="p = 0.05 (顯著門檻)")
ax.axhline(0.10, color="gray", linestyle=":", linewidth=1, label="p = 0.10 (邊緣顯著)")
for bar, p, b in zip(bars, pvals, better):
    label = f"{p:.3f}" + ("\n(SSVS 贏)" if b else "\n(SSVS 輸)")
    ax.text(bar.get_x() + bar.get_width() / 2, p + 0.02, label, ha="center", fontsize=8)
ax.set_ylabel("Diebold-Mariano p-value", fontsize=11)
ax.set_title("SSVS vs GJR-GARCH 的 DM 檢定：5/5 期方向一致，僅 2 期顯著", fontsize=12)
ax.set_ylim(0, 1.05)
ax.legend(fontsize=9)
ax.grid(axis="y", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig2_dm_pvalue_by_period.png", dpi=140, bbox_inches="tight")
plt.close()

# ---------------- Fig 3: avg QLIKE ranking ----------------
fig, ax = plt.subplots(figsize=(8.5, 4.5))
avg = R["full_model_comparison"]
order = sorted(avg.keys(), key=lambda k: avg[k]["avg_QLIKE"])
names = [labels[m] for m in order]
vals = [avg[m]["avg_QLIKE"] for m in order]
bcolors = [colors[m] for m in order]
bars = ax.barh(names, vals, color=bcolors, edgecolor="black", linewidth=0.6)
for b, v in zip(bars, vals):
    ax.text(v + 0.003, b.get_y() + b.get_height() / 2, f"{v:.4f}", va="center", fontsize=9)
ax.set_xlabel("5-period Avg QLIKE  (lower is better)", fontsize=11)
ax.set_title("5 期平均 QLIKE 排名：GJR+VIX 略勝 SSVS（差距僅 0.4%）", fontsize=12)
ax.set_xlim(min(vals) - 0.02, max(vals) + 0.02)
ax.grid(axis="x", alpha=0.3)
plt.tight_layout()
plt.savefig(OUT / "fig3_avg_qlike_ranking.png", dpi=140, bbox_inches="tight")
plt.close()

print("OK fig1/fig2/fig3 written to", OUT)
