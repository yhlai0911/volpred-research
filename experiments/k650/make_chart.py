"""K650 established facts top-N bar chart."""
import json
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parent
results = json.loads((ROOT / "k650_results.json").read_text())
facts = results["core_findings_taxonomy"]["established_facts"]

# Top 6 by citation
top = sorted(facts.items(), key=lambda x: x[1], reverse=True)[:6]
labels = [k for k, _ in top]
counts = [v for _, v in top]

# zh-Hant 友善 label 對照
label_map = {
    "VIX as regime indicator": "VIX 作為波動率\n區間判讀指標",
    "HAR components": "HAR 多時間尺度\n成分",
    "Leverage effect asymmetry": "下跌時波動\n放大（槓桿效應）",
    "VIX sufficiency": "VIX 已涵蓋\n美股大部分訊息",
    "12/VIX strategy": "12/VIX 倉位\n調整法",
    "QLIKE ceiling": "QLIKE 預測誤差\n天花板",
}
zh_labels = [label_map.get(k, k) for k in labels]

plt.rcParams["font.family"] = ["Heiti TC", "PingFang TC", "Arial Unicode MS", "sans-serif"]
plt.rcParams["axes.unicode_minus"] = False

fig, ax = plt.subplots(figsize=(10, 6))
colors = ["#1f4e79", "#2e75b6", "#5b9bd5", "#9dc3e6", "#bdd7ee", "#deebf7"]
bars = ax.barh(range(len(zh_labels)), counts, color=colors[::-1])
ax.set_yticks(range(len(zh_labels)))
ax.set_yticklabels(zh_labels, fontsize=10)
ax.invert_yaxis()
ax.set_xlabel("被引用次數（1399 筆知識條目中）", fontsize=11)
ax.set_title("K650 知識庫盤點：被引用最多的 6 個結論\n(共 16 個 established facts；資料截至 2026-03-29)", fontsize=12)

for bar, c in zip(bars, counts):
    ax.text(bar.get_width() + 3, bar.get_y() + bar.get_height() / 2,
            f"{c} 次", va="center", fontsize=10)

ax.set_xlim(0, max(counts) * 1.15)
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
plt.tight_layout()
out = ROOT / "k650_established_facts_topN.png"
plt.savefig(out, dpi=150, bbox_inches="tight")
print(f"saved {out}")
