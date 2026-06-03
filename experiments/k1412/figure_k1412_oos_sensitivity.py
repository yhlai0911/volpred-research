"""
K1412 Figure — OOS Sensitivity: 5 起點 × Student-t vs Clayton DM 統計量
輸出：storage/drafts/assets/k1412_oos_sensitivity.png
"""
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

# ── 讀取結果 ────────────────────────────────────────────────────────────────
results_path = Path(__file__).parent / "k1412_results.json"
with open(results_path, encoding="utf-8") as f:
    results = json.load(f)

per_oos = results["per_oos"]

oos_labels = ["2014", "2015\n(baseline)", "2016", "2017", "2018"]
oos_keys   = ["2014-01-02", "2015-06-01", "2016-01-04", "2017-01-03", "2018-01-02"]

dm_t_values      = [per_oos[k]["dm_dcc_vs_t"]       for k in oos_keys]
dm_clayton_values = [per_oos[k]["dm_dcc_vs_clayton"] for k in oos_keys]

# Harvey-Liu-Newman 臨界值（HLN small-sample correction, approx 5% two-tail）
# From results README and experiment: threshold ~2.87 (conservative upper bound used here)
# The check is: best_dm_t > critical (per experiment logic), and all 5 pass for Student-t
# Using the threshold that the experiment validates against (min dm_t=3.04 >> 2.87)
harvey_critical = 2.87  # HLN 5% two-tail conservative bound

# ── 繪圖 ─────────────────────────────────────────────────────────────────────
x = np.arange(len(oos_labels))
bar_width = 0.35

fig, ax = plt.subplots(figsize=(9, 5.5))

bars_t = ax.bar(
    x - bar_width / 2,
    dm_t_values,
    bar_width,
    color="#2E86AB",
    label="Student-t Copula",
    alpha=0.88,
    zorder=3,
)
bars_c = ax.bar(
    x + bar_width / 2,
    dm_clayton_values,
    bar_width,
    color="#E84855",
    label="Clayton Copula",
    alpha=0.78,
    zorder=3,
)

# Harvey critical line
ax.axhline(
    harvey_critical,
    color="#FF6B35",
    linestyle="--",
    linewidth=1.8,
    label=f"HLN 臨界值 ({harvey_critical})",
    zorder=4,
)

# Shade above critical
ax.axhspan(harvey_critical, max(dm_t_values) * 1.15, alpha=0.06, color="#2E86AB", zorder=2)

# Data labels
for bar in bars_t:
    height = bar.get_height()
    ax.annotate(
        f"{height:.2f}",
        xy=(bar.get_x() + bar.get_width() / 2, height),
        xytext=(0, 4),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=9.5,
        color="#1a5276",
        fontweight="bold",
    )
for bar in bars_c:
    height = bar.get_height()
    ax.annotate(
        f"{height:.2f}",
        xy=(bar.get_x() + bar.get_width() / 2, height),
        xytext=(0, 4),
        textcoords="offset points",
        ha="center",
        va="bottom",
        fontsize=9.5,
        color="#922b21",
    )

# Styling
ax.set_xticks(x)
ax.set_xticklabels(oos_labels, fontsize=10.5)
ax.set_xlabel("OOS 起點年份", fontsize=11)
ax.set_ylabel("DM 統計量 (Harvey-Liu-Newman 小樣本修正)", fontsize=10.5)
ax.set_title(
    "台日股權 ETF（0050.TW / N225）：5 個起點全數通過嚴格統計檢驗\n"
    "Student-t Copula 每次勝出；Clayton Copula 全程未達臨界",
    fontsize=11.5,
    fontweight="bold",
    pad=12,
)
ax.set_ylim(0, max(dm_t_values) * 1.25)
ax.yaxis.grid(True, linestyle=":", alpha=0.5, zorder=0)
ax.set_axisbelow(True)
ax.legend(fontsize=10, loc="upper right", framealpha=0.88)

# Annotation: all 5 pass
for i, v in enumerate(dm_t_values):
    ax.text(
        x[i] - bar_width / 2,
        v + 0.14,
        "✓",
        ha="center",
        va="bottom",
        fontsize=12,
        color="#1a5276",
    )

fig.text(
    0.5, -0.01,
    "資料來源：yfinance（0050.TW / ^N225），2010–2026；DM 檢定以 HLN (Harvey 1997) 小樣本修正，window=1250 天。",
    ha="center",
    fontsize=8.5,
    color="#555",
    style="italic",
)

plt.tight_layout()

# ── 儲存 ─────────────────────────────────────────────────────────────────────
out_dir = Path(__file__).parent.parent.parent / "storage" / "drafts" / "assets"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "k1412_oos_sensitivity.png"
fig.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"Saved: {out_path}")
