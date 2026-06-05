"""K562 general-audience article chart — 2-panel summary."""
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
RESULTS = ROOT / "k562_k560_sector_validation_results.json"
OUT = ROOT / "k562_general_article_chart.png"

data = json.loads(RESULTS.read_text())

fig, axes = plt.subplots(1, 2, figsize=(13, 5))

scheme_a = data["validation_2_cross_oos"]["Scheme_A"]["periods"]
labels = [f"{p['oos_period'][:4]}–{p['oos_period'][14:18]}" for p in scheme_a]
strat = [p["strat_sharpe"] for p in scheme_a]
bench = [p["bench_sharpe"] for p in scheme_a]

x = range(len(labels))
ax1 = axes[0]
width = 0.35
ax1.bar([i - width / 2 for i in x], strat, width, label="K562 策略", color="#2563eb")
ax1.bar([i + width / 2 for i in x], bench, width, label="SPY 基準", color="#94a3b8")
ax1.set_xticks(list(x))
ax1.set_xticklabels(labels, rotation=0, fontsize=10)
ax1.set_ylabel("Sharpe ratio")
ax1.set_title("Cross-OOS 五個獨立樣本期：策略 5/5 全勝", fontsize=11)
ax1.axhline(y=0, color="black", linewidth=0.5)
ax1.legend(loc="upper left")
ax1.grid(axis="y", alpha=0.3)
for i, (s, b) in enumerate(zip(strat, bench)):
    ax1.text(i - width / 2, s + 0.05, f"{s:.2f}", ha="center", fontsize=9, color="#1e40af")
    ax1.text(i + width / 2, b + 0.05, f"{b:.2f}", ha="center", fontsize=9, color="#64748b")

freq = data["validation_3_rebal_frequency"]
freq_labels = ["每日", "週頻", "月頻"]
freq_keys = ["daily", "weekly", "monthly"]
freq_sharpe = [freq[k]["metrics"]["sharpe"] for k in freq_keys]
freq_bench = freq["daily"]["benchmark_sharpe"]
colors = ["#16a34a" if freq[k]["harvey_pass"] else "#dc2626" for k in freq_keys]

ax2 = axes[1]
ax2.bar(freq_labels, freq_sharpe, color=colors, alpha=0.85)
ax2.axhline(y=freq_bench, color="#94a3b8", linestyle="--", linewidth=1.5, label=f"SPY 基準 {freq_bench:.2f}")
ax2.set_ylabel("Sharpe ratio")
ax2.set_title("再平衡頻率：每日通過、週頻月頻失靈", fontsize=11)
ax2.legend(loc="upper right")
ax2.grid(axis="y", alpha=0.3)
for i, (s, k) in enumerate(zip(freq_sharpe, freq_keys)):
    label = "Harvey 通過" if freq[k]["harvey_pass"] else "Harvey 不過"
    ax2.text(i, s + 0.04, f"{s:.2f}\n{label}", ha="center", fontsize=9)

plt.suptitle("K562 類股輪動加波動目標：八關體檢的兩個關鍵結論", fontsize=12, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT, dpi=120, bbox_inches="tight")
print(f"saved: {OUT}")
