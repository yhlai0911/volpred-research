"""K319 figure generation. Reads k319_decade_results.json, plots decade comparisons."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Traditional Chinese font fallback
for cand in ["PingFang TC", "Heiti TC", "STHeiti", "Microsoft JhengHei",
             "Arial Unicode MS"]:
    try:
        font_manager.findfont(cand, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [cand, "DejaVu Sans"]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

HERE = Path(__file__).resolve().parent
RES = json.loads((HERE.parent / "k319_decade_results.json").read_text())

# Decade order (exclude full-period for the per-decade plots)
DECADES = [
    "2005-2009 (GFC)",
    "2010-2014 (QE Recovery)",
    "2015-2019 (Low-Vol Bull)",
    "2020-2024 (COVID+Rates)",
    "2025-2026 (Current)",
]
DECADE_LABELS = [
    "2005–2009\n(金融海嘯)",
    "2010–2014\n(QE 復甦)",
    "2015–2019\n(低波多頭)",
    "2020–2024\n(疫情+升息)",
    "2025–2026\n(當前)",
]

STRATS = ["SPY B&H", "50/50 B&H", "50/50 + VT (12/VIX)", "50/50 + VT (Step)"]
STRAT_LABELS = ["SPY 買入持有", "50/50 股金配置", "50/50 + VT 公式", "50/50 + VT 階梯"]
COLORS = ["#7f8c8d", "#3498db", "#e67e22", "#27ae60"]


def collect(metric: str) -> np.ndarray:
    """Returns shape (n_strategies, n_decades) array of metric."""
    out = np.zeros((len(STRATS), len(DECADES)))
    for i, s in enumerate(STRATS):
        for j, d in enumerate(DECADES):
            out[i, j] = RES["decades"][d][s][metric]
    return out


# ─────────────────────────────────────────────
# Figure 1: Sharpe & MDD bar charts side-by-side
# ─────────────────────────────────────────────
sharpe = collect("Sharpe")
mdd = collect("MDD")

fig, axes = plt.subplots(1, 2, figsize=(15, 6.5))
x = np.arange(len(DECADES))
width = 0.2

ax = axes[0]
for i, s in enumerate(STRATS):
    ax.bar(x + (i - 1.5) * width, sharpe[i], width, label=STRAT_LABELS[i],
           color=COLORS[i], edgecolor="black", linewidth=0.4)
ax.set_xticks(x)
ax.set_xticklabels(DECADE_LABELS, fontsize=9)
ax.set_ylabel("Sharpe 比率", fontsize=11)
ax.set_title("各年代 Sharpe 比率比較", fontsize=12, fontweight="bold")
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=8, loc="upper left")

ax = axes[1]
for i, s in enumerate(STRATS):
    ax.bar(x + (i - 1.5) * width, mdd[i], width, label=STRAT_LABELS[i],
           color=COLORS[i], edgecolor="black", linewidth=0.4)
ax.set_xticks(x)
ax.set_xticklabels(DECADE_LABELS, fontsize=9)
ax.set_ylabel("最大回撤 MDD (%)", fontsize=11)
ax.set_title("各年代最大回撤比較（越小越好）", fontsize=12, fontweight="bold")
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=8, loc="lower left")

plt.suptitle("十年又十年：四種策略在五個年代的表現",
             fontsize=14, fontweight="bold", y=1.00)
plt.tight_layout()
plt.savefig(HERE / "fig1_sharpe_mdd_by_decade.png", dpi=160, bbox_inches="tight")
plt.close()

# ─────────────────────────────────────────────
# Figure 2: CAGR heatmap (strategies × decades)
# ─────────────────────────────────────────────
cagr = collect("CAGR")

fig, ax = plt.subplots(figsize=(10, 5))
im = ax.imshow(cagr, cmap="RdYlGn", aspect="auto", vmin=-2, vmax=32)
ax.set_xticks(np.arange(len(DECADES)))
ax.set_xticklabels(DECADE_LABELS, fontsize=10)
ax.set_yticks(np.arange(len(STRATS)))
ax.set_yticklabels(STRAT_LABELS, fontsize=10)

for i in range(len(STRATS)):
    for j in range(len(DECADES)):
        v = cagr[i, j]
        color = "white" if v > 22 or v < 3 else "black"
        ax.text(j, i, f"{v:.1f}%", ha="center", va="center",
                color=color, fontsize=10, fontweight="bold")

ax.set_title("年化報酬率 CAGR 熱圖（策略 × 年代）",
             fontsize=13, fontweight="bold", pad=12)
cbar = plt.colorbar(im, ax=ax, shrink=0.8)
cbar.set_label("CAGR (%)", fontsize=10)
plt.tight_layout()
plt.savefig(HERE / "fig2_cagr_heatmap.png", dpi=160, bbox_inches="tight")
plt.close()

# ─────────────────────────────────────────────
# Figure 3: Worst-month damage by decade
# ─────────────────────────────────────────────
worst = collect("Worst_Month")

fig, ax = plt.subplots(figsize=(11, 6))
for i, s in enumerate(STRATS):
    ax.bar(x + (i - 1.5) * width, worst[i], width, label=STRAT_LABELS[i],
           color=COLORS[i], edgecolor="black", linewidth=0.4)
ax.set_xticks(x)
ax.set_xticklabels(DECADE_LABELS, fontsize=10)
ax.set_ylabel("單月最大跌幅 (%)", fontsize=11)
ax.set_title("各年代「最慘一個月」損失（VT 把恐慌月的損傷壓下來了嗎？）",
             fontsize=12, fontweight="bold")
ax.axhline(0, color="black", linewidth=0.5)
ax.grid(axis="y", alpha=0.3)
ax.legend(fontsize=9, loc="lower right")
plt.tight_layout()
plt.savefig(HERE / "fig3_worst_month_by_decade.png", dpi=160, bbox_inches="tight")
plt.close()

print("Figures generated:")
for f in sorted(HERE.glob("*.png")):
    print(f"  {f.name}  ({f.stat().st_size // 1024} KB)")
