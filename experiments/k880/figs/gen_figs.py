#!/usr/bin/env python3
"""Generate K880 article figures: qlike_bar.png and cross_recursion_value.png"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Figure 1: OOS QLIKE bar chart ──────────────────────────────────────────
models = ["HAR", "Separate", "GJR", "PRG_Basic", "PRG_Extended"]
qlike_vals = [1.4635, 0.8672, 0.8542, 0.7577, 0.7478]

colors = ["#c0392b", "#e67e22", "#e67e22", "#3498db", "#1a6faf"]
# HAR = red (worst), Separate = orange, GJR = orange, PRG_Basic = blue, PRG_Extended = dark blue (winner)
bar_colors = ["#c0392b", "#e67e22", "#e67e22", "#5dade2", "#1a6faf"]
edge_colors = ["#922b21", "#ca6f1e", "#ca6f1e", "#2e86c1", "#154360"]

fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.barh(models, qlike_vals, color=bar_colors, edgecolor=edge_colors, linewidth=1.2, height=0.55)

# Highlight winner
bars[-1].set_linewidth(2.5)

# Add value labels
for bar, val in zip(bars, qlike_vals):
    ax.text(val + 0.01, bar.get_y() + bar.get_height() / 2,
            f"{val:.4f}", va="center", ha="left", fontsize=10.5, fontweight="bold")

ax.set_xlabel("QLIKE（越低越好）", fontsize=12)
ax.set_title("五模型 OOS QLIKE — SPY 2019–2026（1823 天）", fontsize=13, fontweight="bold", pad=12)
ax.set_xlim(0, 1.65)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.tick_params(axis="y", labelsize=11)
ax.tick_params(axis="x", labelsize=10)

# Legend patches
winner_patch = mpatches.Patch(color="#1a6faf", label="PRG_Extended（最佳）")
baseline_patch = mpatches.Patch(color="#e67e22", label="GJR / Separate（基準）")
worst_patch = mpatches.Patch(color="#c0392b", label="HAR（最差）")
ax.legend(handles=[winner_patch, baseline_patch, worst_patch],
          loc="lower right", fontsize=9.5, framealpha=0.85)

# Annotation arrow: PRG_Extended wins
ax.annotate("", xy=(0.7478, 4), xytext=(0.8542, 4),
            arrowprops=dict(arrowstyle="->", color="#154360", lw=1.8))
ax.text(0.80, 4.28, "QLIKE −12.5%\nvs GJR", ha="center", va="bottom",
        fontsize=8.5, color="#154360")

ax.text(0.02, -0.07, "資料來源：yfinance SPY + ^VIX（K880）",
        transform=ax.transAxes, fontsize=8, color="#666")

plt.tight_layout()
fig.savefig(os.path.join(OUTPUT_DIR, "qlike_bar.png"), dpi=150, bbox_inches="tight")
plt.close(fig)
print("saved qlike_bar.png")

# ── Figure 2: DM t-stat bars with Harvey critical lines ────────────────────
comparisons = ["PRG_Extended\nvs GJR", "PRG_Extended\nvs Separate GARCH"]
t_stats = [6.003887940674553, -6.689785527256411]

fig2, ax2 = plt.subplots(figsize=(7, 4.5))

bar_colors2 = ["#1a6faf", "#8e44ad"]
bars2 = ax2.bar(comparisons, t_stats, color=bar_colors2, edgecolor=["#154360", "#6c3483"],
                linewidth=1.5, width=0.45)

# Add value labels on bars
for bar, val in zip(bars2, t_stats):
    ypos = val + 0.2 if val > 0 else val - 0.45
    ax2.text(bar.get_x() + bar.get_width() / 2, ypos,
             f"t = {val:.2f}", ha="center", va="bottom" if val > 0 else "top",
             fontsize=12, fontweight="bold", color="white" if abs(val) > 1 else "black",
             bbox=dict(boxstyle="round,pad=0.2", facecolor=bar.get_facecolor(), alpha=0.85))

# Harvey critical lines
ax2.axhline(2.58, color="#e74c3c", linestyle="--", linewidth=1.5, label="Harvey 1% 顯著（±2.58）")
ax2.axhline(-2.58, color="#e74c3c", linestyle="--", linewidth=1.5)
ax2.axhline(1.96, color="#f39c12", linestyle=":", linewidth=1.2, label="Harvey 5% 顯著（±1.96）")
ax2.axhline(-1.96, color="#f39c12", linestyle=":", linewidth=1.2)
ax2.axhline(0, color="#aaa", linewidth=0.8)

ax2.set_ylabel("DM t-統計量", fontsize=12)
ax2.set_title("PRG_Extended 優勢：Diebold-Mariano 檢定 t 值\n（正值 = PRG_Extended 更好；負值因比對方向反轉同意義）",
              fontsize=11, fontweight="bold", pad=10)
ax2.spines["top"].set_visible(False)
ax2.spines["right"].set_visible(False)
ax2.tick_params(axis="x", labelsize=10.5)
ax2.tick_params(axis="y", labelsize=10)
ax2.set_ylim(-9.5, 9.5)

# Labels for critical lines
ax2.text(1.42, 2.75, "1% 顯著 (2.58)", color="#e74c3c", fontsize=8.5, va="bottom")
ax2.text(1.42, -3.0, "1% 顯著 (−2.58)", color="#e74c3c", fontsize=8.5, va="top")

ax2.legend(loc="upper right", fontsize=9, framealpha=0.85)

# Harvey PASS label
for i, (bar, val) in enumerate(zip(bars2, t_stats)):
    ax2.text(bar.get_x() + bar.get_width() / 2, 8.5,
             "Harvey PASS ✓", ha="center", va="center", fontsize=9.5,
             color="#27ae60", fontweight="bold")

ax2.text(0.02, -0.1, "資料來源：yfinance SPY + ^VIX（K880）；DM 檢定依 Harvey et al. (1997)",
         transform=ax2.transAxes, fontsize=7.5, color="#666")

plt.tight_layout()
fig2.savefig(os.path.join(OUTPUT_DIR, "cross_recursion_value.png"), dpi=150, bbox_inches="tight")
plt.close(fig2)
print("saved cross_recursion_value.png")
print("All figures done.")
