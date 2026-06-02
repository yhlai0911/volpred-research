"""
K802 Article Chart Generator
生成給一般讀者文章用的圖表：VaR 違反率 + Trinity 結果條形圖
"""
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from pathlib import Path

# Load results
results_path = Path(__file__).parent / "k802_gjr_skewt_results.json"
with open(results_path) as f:
    data = json.load(f)

var_results = data["var_backtest_results"]

# ── 圖 1：違反率 bar chart + 監管門檻線 ──────────────────────────────────
models = ["GJR+Normal", "GJR+StudentT", "GJR+SkewedT", "GARCH+Normal", "GJR+FHS"]
labels = ["GJR\n常態分配", "GJR\nStudent-t", "GJR\nSkewed-t", "GARCH\n常態分配", "GJR\nFHS"]
violation_rates = [var_results[m]["violation_rate"] * 100 for m in models]
basels = [var_results[m]["basel_traffic_light"] for m in models]

color_map = {"green": "#2ecc71", "yellow": "#f39c12", "red": "#e74c3c"}
bar_colors = [color_map[b] for b in basels]

fig, ax = plt.subplots(figsize=(9, 5))
bars = ax.bar(labels, violation_rates, color=bar_colors, edgecolor="white", width=0.55, zorder=3)

# 目標 1% 線
ax.axhline(y=1.0, color="#2c3e50", linewidth=1.8, linestyle="--", zorder=4, label="目標：1%")
# Basel yellow 門檻（1.5%，約對應 7.5/500 violations at 99% CI upper bound for green）
ax.axhline(y=1.5, color="#f39c12", linewidth=1.2, linestyle=":", zorder=4, label="Basel 黃燈門檻")

# 標數值
for bar, rate, m in zip(bars, violation_rates, models):
    n_viol = var_results[m]["n_violations"]
    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.04,
            f"{n_viol}/502\n({rate:.2f}%)",
            ha="center", va="bottom", fontsize=9, fontweight="bold",
            color="#2c3e50")

# 圖例 patch
green_patch = mpatches.Patch(color="#2ecc71", label="Basel 綠燈 ✓ 通過")
yellow_patch = mpatches.Patch(color="#f39c12", label="Basel 黃燈 ✗ 未通過")
ax.legend(handles=[green_patch, yellow_patch],
          loc="upper right", fontsize=9, framealpha=0.9)

ax.set_ylabel("VaR 1% 違反率（%）", fontsize=10)
ax.set_title("GJR-GARCH 各分配假設的 VaR 違反率\nSPY 樣本外 2023–2024（502 觀測值）",
             fontsize=11, fontweight="bold")
ax.set_ylim(0, 2.5)
ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
ax.set_axisbelow(True)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)

plt.rcParams["font.sans-serif"] = ["Noto Sans CJK TC", "PingFang TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

plt.tight_layout()
out_path = Path(__file__).parent / "k802_violation_rate_chart.png"
plt.savefig(out_path, dpi=150, bbox_inches="tight")
print(f"Chart saved: {out_path}")
plt.close()

# ── 圖 2：Trinity PASS/FAIL 視覺化（Kupiec + Christoffersen + Basel）──────
fig2, ax2 = plt.subplots(figsize=(9, 4.5))

checks = ["Kupiec\n(無條件覆蓋)", "Christoffersen\n(獨立性)", "Basel\n交通燈"]

# Build matrix: rows=models, cols=checks
matrix = []
for m in models:
    r = var_results[m]
    kupiec_pass = r["kupiec"]["pass"]
    chris_pass = r["christoffersen"]["pass"]
    basel_green = r["basel_traffic_light"] == "green"
    matrix.append([kupiec_pass, chris_pass, basel_green])

matrix_arr = np.array(matrix, dtype=float)  # 1=PASS, 0=FAIL

im = ax2.imshow(matrix_arr, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")

ax2.set_xticks(range(len(checks)))
ax2.set_xticklabels(checks, fontsize=9)
ax2.set_yticks(range(len(labels)))
ax2.set_yticklabels(labels, fontsize=9)

for i in range(len(models)):
    for j in range(len(checks)):
        val = matrix[i][j]
        txt = "PASS" if val else "FAIL"
        color = "white" if not val else "#1a5e1a"
        ax2.text(j, i, txt, ha="center", va="center",
                 fontsize=10, fontweight="bold", color=color)

ax2.set_title("VaR Trinity 檢定結果（SPY OOS 2023–2024）",
              fontsize=11, fontweight="bold")
ax2.set_xlabel("檢定項目", fontsize=10)

plt.tight_layout()
out_path2 = Path(__file__).parent / "k802_trinity_heatmap.png"
plt.savefig(out_path2, dpi=150, bbox_inches="tight")
print(f"Chart saved: {out_path2}")
plt.close()

print("Done. Both charts generated.")
