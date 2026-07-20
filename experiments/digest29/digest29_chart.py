"""Digest #29 hook chart: depth vs radius of the July 2026 chip drawdown."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from volpred.charts.article_charts import _setup_style

_setup_style()

res = json.load(open("experiments/digest29/digest29_results.json"))
s = res["series"]

fig, axes = plt.subplots(1, 2, figsize=(13, 5.4))

# Panel 1 — radius: drawdown from 2026 peak
labels = ["費城半導體\n^SOX", "標普 500\n^GSPC", "能源\nXLE", "工業\nXLI", "金融\nXLF"]
keys = ["^SOX", "^GSPC", "XLE", "XLI", "XLF"]
vals = [s[k]["drawdown_from_peak_pct"] for k in keys]
colors = ["#c0392b"] + ["#7f8c8d"] * 4
b = axes[0].barh(labels[::-1], vals[::-1], color=colors[::-1], height=0.6)
axes[0].set_xlabel("距 2026 年高點的回撤（%）")
axes[0].set_title("震央範圍：跌的只有晶片", fontsize=14, fontweight="bold", pad=12)
axes[0].axvline(0, color="black", lw=0.8)
for rect, v in zip(b, vals[::-1]):
    axes[0].text(v - 0.9, rect.get_y() + rect.get_height() / 2, f"{v:.2f}%",
                 va="center", ha="right", fontsize=10, fontweight="bold")
axes[0].set_xlim(-24, 3)

# Panel 2 — depth: 20d realized vol, now vs 60 sessions ago
x = ["費半 ^SOX", "標普 500 SPY"]
now = [s["^SOX"]["rv20_ann_pct"], s["SPY"]["rv20_ann_pct"]]
before = [s["^SOX"]["rv20_ann_pct_60d_ago"], s["SPY"]["rv20_ann_pct_60d_ago"]]
xi = range(len(x))
axes[1].bar([i - 0.2 for i in xi], before, width=0.4, label="60 個交易日前", color="#95a5a6")
axes[1].bar([i + 0.2 for i in xi], now, width=0.4, label="目前", color="#c0392b")
axes[1].set_xticks(list(xi))
axes[1].set_xticklabels(x)
axes[1].set_ylabel("20 日已實現波動率（年化 %）")
axes[1].set_title("震源深度：晶片震幅放大，大盤反而變安靜", fontsize=14, fontweight="bold", pad=12)
axes[1].legend()
for i, (bf, nw) in enumerate(zip(before, now)):
    axes[1].text(i - 0.2, bf + 1.4, f"{bf:.1f}", ha="center", fontsize=9)
    axes[1].text(i + 0.2, nw + 1.4, f"{nw:.1f}", ha="center", fontsize=9, fontweight="bold")
    ratio = nw / bf
    axes[1].text(i, max(bf, nw) + 6.5, f"×{ratio:.2f}", ha="center", fontsize=12,
                 fontweight="bold", color="#c0392b" if ratio > 1 else "#27ae60")
axes[1].set_ylim(0, 82)

fig.suptitle("震央定位：2026-07-17 收盤，資料來源 yfinance", fontsize=10, y=0.02, color="#555")
plt.tight_layout(rect=[0, 0.03, 1, 1])
plt.savefig("experiments/digest29/digest29_epicenter.png", dpi=150, bbox_inches="tight")
print("saved")
