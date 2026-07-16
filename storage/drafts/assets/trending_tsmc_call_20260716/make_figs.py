"""兩張圖：(a) TSM vs 2330.TW 近 30 日走勢標法說日；(b) 隱含 vs 實際 move + IV 前後對比."""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = ["Heiti TC", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

OUT = "/Users/yhlai0911/volpred-research/storage/drafts/assets/trending_tsmc_call_20260716"

tsm = pd.read_csv(f"{OUT}/tsm_daily.csv", index_col=0, parse_dates=True)["Close"].dropna()
twn = pd.read_csv(f"{OUT}/twn2330_daily.csv", index_col=0, parse_dates=True)["Close"].dropna()

# ---- 圖 a：近 30 個交易日, 標法說日 ----
tsm30, twn30 = tsm.tail(30), twn.tail(30)
base_date = max(tsm30.index[0], twn30.index[0])
tsm30 = tsm30[tsm30.index >= base_date]
twn30 = twn30[twn30.index >= base_date]
tsm_n = tsm30 / tsm30.iloc[0] * 100
twn_n = twn30 / twn30.iloc[0] * 100

PRE_MKT = 403.30           # TSM 2026-07-16 盤前 (yfinance preMarketPrice)
pre_n = PRE_MKT / tsm30.iloc[0] * 100
call_day = pd.Timestamp("2026-07-16")

fig, ax = plt.subplots(figsize=(9, 5))
ax.plot(tsm_n.index, tsm_n.values, lw=2, color="#1f77b4",
        label=f"TSM ADR（{tsm30.index[0].date()}=100）")
ax.plot(twn_n.index, twn_n.values, lw=2, color="#d62728",
        label=f"2330.TW（{twn30.index[0].date()}=100）")
ax.scatter([call_day], [pre_n], marker="*", s=220, color="#1f77b4", zorder=5,
           edgecolor="black", linewidth=0.6)
ax.annotate(f"TSM 7/16 盤前 {PRE_MKT}（約 -3.9%）",
            xy=(call_day, pre_n), xytext=(-190, 22), textcoords="offset points",
            fontsize=9.5, color="#1f77b4", fontweight="bold",
            arrowprops=dict(arrowstyle="->", color="#1f77b4", lw=1))
ax.axvline(call_day, color="gray", ls="--", lw=1.2)
ymin, ymax = ax.get_ylim()
ax.set_ylim(ymin - 1.5, ymax)
ax.text(call_day, ymax - 0.3, "7/16 法說會 ", va="top", ha="right",
        fontsize=10, color="dimgray")
ax.set_title("台積電法說會前 30 個交易日：ADR 與台股現貨走勢", fontsize=13)
ax.set_ylabel("標準化價格（期初 = 100）")
ax.legend(loc="lower left", fontsize=9)
ax.grid(alpha=0.3)
fig.text(0.99, 0.01, "資料：yfinance 日線；TSM 盤前為 2026-07-16 台北 18:00 左右快照",
         ha="right", fontsize=7.5, color="gray")
fig.tight_layout()
fig.savefig(f"{OUT}/fig_a_price_30d.png", dpi=150)
plt.close(fig)

# ---- 圖 b：隱含 vs 實際 move + IV 對比 ----
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5))

labels = ["前夕文估計\n事件隱含 move\n(7/8 定價)", "7/15 收盤\nATM straddle\n隱含 move",
          "歷史 8 次法說\n平均實際 move", "歷史 8 次法說\n中位數", "本次實際反應\n(7/16 盤前)"]
vals = [4.0, 4.23, 4.89, 3.73, 3.9]
colors = ["#8ea9c9", "#4c72b0", "#c9b18e", "#c9b18e", "#d62728"]
bars = ax1.bar(range(len(vals)), vals, color=colors, width=0.62)
for b, v in zip(bars, vals):
    ax1.text(b.get_x() + b.get_width() / 2, v + 0.06, f"{v:.2f}%",
             ha="center", fontsize=10, fontweight="bold")
ax1.set_xticks(range(len(labels)))
ax1.set_xticklabels(labels, fontsize=8.5)
ax1.set_ylabel("單日絕對漲跌幅（%）")
ax1.set_title("市場替法說會定的價 vs 實際跳動", fontsize=12)
ax1.axhline(3.9, color="#d62728", ls=":", lw=1)
ax1.grid(axis="y", alpha=0.3)

# 右圖：IV 時間軸 / 期限結構
x = [0, 1]
iv_717 = [63.5, 68.8]   # 7/17 到期 ATM IV: 7/8 定價 → 7/15 收盤
ax2.plot(x, iv_717, "o-", lw=2, color="#4c72b0", label="7/17 到期 ATM IV")
ax2.plot([1], [53.8], "s", ms=9, color="#55a868", label="7/24 到期 ATM IV（7/15 收盤）")
ax2.plot([1], [51.8], "^", ms=9, color="#8172b2", label="8/21 到期 ATM IV（7/15 收盤）")
ax2.axhline(59.1, color="gray", ls="--", lw=1.2)
ax2.text(0.02, 59.1 + 0.5, "20 日已實現波動率 59.1%", fontsize=8.5, color="gray")
for xi, yi in zip(x, iv_717):
    ax2.annotate(f"{yi:.1f}%", (xi, yi), textcoords="offset points",
                 xytext=(0, 9), ha="center", fontsize=10, fontweight="bold", color="#4c72b0")
ax2.annotate("53.8%", (1, 53.8), textcoords="offset points", xytext=(10, -4),
             fontsize=9, color="#55a868")
ax2.annotate("51.8%", (1, 51.8), textcoords="offset points", xytext=(10, -4),
             fontsize=9, color="#8172b2")
ax2.set_xticks(x)
ax2.set_xticklabels(["7/8 盤後\n（前夕文資料截點）", "7/15 收盤\n（法說前最後交易日）"], fontsize=9)
ax2.set_ylabel("年化隱含波動率（%）")
ax2.set_ylim(45, 75)
ax2.set_xlim(-0.25, 1.45)
ax2.set_title("法說前 ATM 隱含波動率：事件溢價集中在最前端", fontsize=12)
ax2.legend(fontsize=8, loc="lower left")
ax2.grid(alpha=0.3)

fig.text(0.99, 0.01,
         "資料：yfinance TSM 選擇權（7/15 最後成交價反推 BS IV）；法說後 IV crush 待美股 7/16 開盤才可觀測",
         ha="right", fontsize=7.5, color="gray")
fig.tight_layout(rect=[0, 0.03, 1, 1])
fig.savefig(f"{OUT}/fig_b_implied_vs_actual.png", dpi=150)
plt.close(fig)
print("figs done")
