"""Charts for trending repost: mega-cap crowded-trade skew evidence."""
import json
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

BASE = "storage/drafts/trending_ai_capex_skew"
with open(f"{BASE}/skew_results.json") as f:
    data = json.load(f)["results"]

by = {r["ticker"]: r for r in data}
singles = ["NVDA", "MSFT", "GOOGL", "META", "AMZN", "AAPL", "TSLA"]
index = ["QQQ", "SPY"]

plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
                     "font.family": "Heiti TC", "axes.unicode_minus": False})

# ---- Fig 1: skew single names vs index ----
fig, ax = plt.subplots(figsize=(9, 5))
labels = singles + index
skews = [by[t]["skew_90_110"] * 100 for t in labels]
colors = ["#4C72B0"] * len(singles) + ["#C44E52"] * len(index)
bars = ax.bar(labels, skews, color=colors)
ax.axhline(0, color="#333", lw=0.8)
ax.set_ylabel("Skew = IV(90% put) − IV(110% call)  (%)")
ax.set_title("Tail-risk hedging is priced at the index, not single names\n"
             "指數 skew 陡、個股 skew 平甚至倒掛（~30D 到期）", fontsize=12)
for b, v in zip(bars, skews):
    ax.text(b.get_x() + b.get_width() / 2, v + (0.3 if v >= 0 else -0.6),
            f"{v:+.1f}", ha="center", fontsize=9)
from matplotlib.patches import Patch
ax.legend(handles=[Patch(color="#4C72B0", label="Mega-cap 個股"),
                   Patch(color="#C44E52", label="Index ETF")], loc="upper left")
fig.tight_layout()
fig.savefig(f"{BASE}/fig1_skew.png", dpi=130)
plt.close(fig)

# ---- Fig 2: two-panel P/C OI ratio + IV-RV gap ----
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

pc = [by[t]["put_call_oi_ratio"] for t in labels]
colors2 = ["#4C72B0"] * len(singles) + ["#C44E52"] * len(index)
b1 = ax1.bar(labels, pc, color=colors2)
ax1.axhline(1.0, color="#888", ls="--", lw=1, label="P/C = 1（多空對沖平衡）")
ax1.set_ylabel("Put / Call open-interest ratio")
ax1.set_title("個股 call-heavy（<1），指數 put-heavy（>1）")
for b, v in zip(b1, pc):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.05, f"{v:.2f}",
             ha="center", fontsize=9)
ax1.legend()

gaps = [by[t]["iv_rv_gap"] * 100 for t in singles]
gcolors = ["#C44E52" if g < 0 else "#55A868" for g in gaps]
b2 = ax2.bar(singles, gaps, color=gcolors)
ax2.axhline(0, color="#333", lw=0.8)
ax2.set_ylabel("IV − RV20  (percentage points)")
ax2.set_title("負值 = 選擇權低估近期已實現波動（complacent）")
for b, v in zip(b2, gaps):
    ax2.text(b.get_x() + b.get_width() / 2, v + (0.4 if v >= 0 else -1.0),
             f"{v:+.1f}", ha="center", fontsize=9)
fig.suptitle("市場對系統性風險過度對沖、對個股尾部風險卻鬆懈（~30D 到期，2026-07-03）",
             fontsize=12)
fig.tight_layout(rect=[0, 0, 1, 0.96])
fig.savefig(f"{BASE}/fig2_pc_ivrv.png", dpi=130)
plt.close(fig)

print("wrote fig1_skew.png + fig2_pc_ivrv.png")
