"""K1074 一般讀者向對比圖 — 純繪圖腳本，不做任何新計算。

所有數字直接讀自 experiments/k1074/k1074_results.json（既有實驗結果，
已通過 Codex review，見 README.md 第 9 節）。本腳本只負責把研究向的
7-策略 log-scale 權益曲線，轉成一般讀者容易理解的 2 張長條對比圖：

1. k1074_general_sharpe_bar.png — 扣成本後 Net Sharpe 對比（12/VIX vs A4f vs GJR）
2. k1074_general_turnover_bar.png — 年化周轉倍數對比

用途：daily_article（一般讀者向）文章配圖。不含隨機程序，無需 seed。
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from plot_style import apply_cjk_style

apply_cjk_style()

HERE = Path(__file__).parent
RESULTS = json.loads((HERE / "k1074_results.json").read_text())

metrics = RESULTS["metrics"]

# 三個核心策略（散戶關心的對比：簡單規則 vs 兩種 GARCH 精密模型）
labels = ["12/VIX\n(最簡單規則)", "A4f-VT\n(精密 GARCH)", "GJR-VT\n(標準 GARCH)"]
colors = ["#2E7D32", "#C62828", "#F9A825"]  # green=winner, red=complex loser, amber=middle

net_sharpe = [
    metrics["A_12VIX_net"]["sharpe"],
    metrics["B_A4f_net"]["sharpe"],
    metrics["C_GJR_net"]["sharpe"],
]
annual_turnover = [
    metrics["A_12VIX_net"]["annual_notional"],
    metrics["B_A4f_net"]["annual_notional"],
    metrics["C_GJR_net"]["annual_notional"],
]

# ---- Chart 1: Net Sharpe bar ----
fig, ax = plt.subplots(figsize=(7.5, 5.5))
bars = ax.bar(labels, net_sharpe, color=colors, width=0.55, edgecolor="white")
for bar, val in zip(bars, net_sharpe):
    ax.text(bar.get_x() + bar.get_width() / 2, val + 0.012, f"{val:.3f}",
            ha="center", va="bottom", fontsize=15, fontweight="bold")
ax.set_ylabel("扣交易成本後 Sharpe 比率（Net Sharpe）", fontsize=12)
ax.set_title("扣掉交易成本後，最簡單的規則反而贏\nSPY 2013–2026，13年樣本，交易成本 5bp", fontsize=13)
ax.set_ylim(0, max(net_sharpe) * 1.25)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.axhline(0, color="black", linewidth=0.8)
ax.annotate("最高", xy=(0, net_sharpe[0]), xytext=(0, net_sharpe[0] + 0.09),
            ha="center", fontsize=11, color="#2E7D32", fontweight="bold")
fig.tight_layout()
out1 = Path(__file__).resolve().parent / "k1074_general_sharpe_bar.png"
fig.savefig(out1, dpi=150)
plt.close(fig)

# ---- Chart 2: Annual turnover bar ----
fig, ax = plt.subplots(figsize=(7.5, 5.5))
bars = ax.bar(labels, annual_turnover, color=colors, width=0.55, edgecolor="white")
for bar, val in zip(bars, annual_turnover):
    ax.text(bar.get_x() + bar.get_width() / 2, val + 0.3, f"{val:.1f}×",
            ha="center", va="bottom", fontsize=15, fontweight="bold")
ax.set_ylabel("年化周轉倍數（換手率，倍數越高交易越頻繁）", fontsize=12)
ax.set_title("模型越精密，換手越頻繁\nA4f 的年化周轉是 12/VIX 的 1.68 倍", fontsize=13)
ax.set_ylim(0, max(annual_turnover) * 1.3)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
out2 = Path(__file__).resolve().parent / "k1074_general_turnover_bar.png"
fig.savefig(out2, dpi=150)
plt.close(fig)

print(f"Saved: {out1}")
print(f"Saved: {out2}")
print(f"Net Sharpe: 12/VIX={net_sharpe[0]:.3f}  A4f={net_sharpe[1]:.3f}  GJR={net_sharpe[2]:.3f}")
print(f"Annual turnover: 12/VIX={annual_turnover[0]:.2f}x  A4f={annual_turnover[1]:.2f}x  GJR={annual_turnover[2]:.2f}x")
