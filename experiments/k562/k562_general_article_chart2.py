"""K562 chart 2 — momentum window curve + transaction cost sensitivity."""
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
RESULTS = ROOT / "k562_k560_sector_validation_results.json"
OUT = ROOT / "k562_general_article_chart2.png"

data = json.loads(RESULTS.read_text())

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

mw = data["validation_4_momentum_window"]
windows = sorted(mw.keys(), key=lambda k: int(k.replace("d", "")))
days = [int(k.replace("d", "")) for k in windows]
sharpes = [mw[k]["metrics"]["sharpe"] for k in windows]

ax1 = axes[0]
ax1.plot(days, sharpes, marker="o", color="#2563eb", linewidth=2, markersize=8)
ax1.set_xlabel("動能視窗（交易日）")
ax1.set_ylabel("Sharpe ratio")
ax1.set_title("動能視窗敏感度：20 天最強、視窗越長越弱", fontsize=11)
ax1.grid(alpha=0.3)
ax1.axhline(y=1.34, color="#94a3b8", linestyle="--", linewidth=1, label="SPY 基準 1.34")
ax1.legend(loc="upper right")
for d, s in zip(days, sharpes):
    ax1.annotate(f"{s:.2f}", (d, s), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9)

tx = data["validation_5_transaction_costs"]
tx_keys = ["0bp_daily", "5bp_daily", "10bp_daily", "20bp_daily"]
tx_labels = ["0 bp", "5 bp", "10 bp", "20 bp"]
tx_sharpes = [tx[k]["metrics"]["sharpe"] for k in tx_keys if k in tx]
tx_drags = [tx[k]["annual_drag"] * 100 for k in tx_keys if k in tx]

ax2 = axes[1]
colors2 = ["#16a34a", "#16a34a", "#eab308", "#dc2626"]
bars = ax2.bar(tx_labels[: len(tx_sharpes)], tx_sharpes, color=colors2[: len(tx_sharpes)], alpha=0.85)
ax2.axhline(y=1.34, color="#94a3b8", linestyle="--", linewidth=1.5, label="SPY 基準 1.34")
ax2.set_xlabel("單邊交易成本")
ax2.set_ylabel("Sharpe ratio")
ax2.set_title("交易成本敏感度：20bp 之內仍勝基準", fontsize=11)
ax2.legend(loc="upper right")
ax2.grid(axis="y", alpha=0.3)
for i, (s, d) in enumerate(zip(tx_sharpes, tx_drags)):
    ax2.text(i, s + 0.05, f"{s:.2f}\n年化拖累 {d:.2f}%", ha="center", fontsize=9)

plt.suptitle("K562 動能視窗 + 交易成本的敏感度分析", fontsize=12, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"saved: {OUT}")
